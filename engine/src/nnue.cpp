#include "nnue.h"

#include "mem.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <vector>
#include <xmmintrin.h>
#if defined(__AVX2__) && defined(__FMA__)
#include <immintrin.h>
#define JQ_AVX2 1
#endif

namespace jq::nnue {

int g_kingBuckets = 1;
int g_urnBase = NUM_PIECE_FEATURES;

namespace {

struct AlignedFree {
    void operator()(float* p) const { std::free(p); }
};
using Buf = std::unique_ptr<float[], AlignedFree>;
Buf alloc(std::size_t n) {
    const std::size_t bytes = ((n * sizeof(float) + 63) / 64) * 64;
    float* p = static_cast<float*>(std::aligned_alloc(64, bytes ? bytes : 64));
    std::memset(p, 0, bytes ? bytes : 64);
    return Buf(p);
}

// In-memory layout: FT rows padded to `stride` floats (multiple of 8; column ft = PSQT).
// L1/L2 weights stored transposed [input][output] for broadcast-FMA accumulation.
// Quantization: FT weights/accumulators at scale QF; activations are (acc+1)>>1 in [0, QA];
// L1 weights are int8 with a per-output-row scale (127 / row absmax).
constexpr int QA = 127, QF = 254;

struct AlignedFreeI {
    void operator()(void* p) const { std::free(p); }
};
template <typename T>
std::unique_ptr<T[], AlignedFreeI> alloc_t(std::size_t n) {
    return std::unique_ptr<T[], AlignedFreeI>(static_cast<T*>(alloc_large(n * sizeof(T))));  // FT weights: one huge page
}

struct Net {
    int ft = 0, l1 = 0, l2 = 0, stride = 0, qstride = 0;
    float outScale = 400.0f;
    Buf ftW, ftB, l1T, l1B, l2T, l2B, outW;
    float outB = 0.0f;
    // Quantized copies.
    std::unique_ptr<int16_t[], AlignedFreeI> ftWq, ftBq;
    std::unique_ptr<int8_t[], AlignedFreeI> l1q;  // [L1][2F], natural input order
    Buf l1qInv;                                   // per-row dequantisation factor 1 / (QA * rowScale)
    bool canQuant = false;
};

Net net;
bool g_loaded = false;
bool g_quantWanted = true;
bool g_quant = false;

bool read_floats(FILE* f, std::vector<float>& v, std::size_t n) {
    v.resize(n);
    return std::fread(v.data(), sizeof(float), n, f) == n;
}

inline const float* row(int f) { return net.ftW.get() + std::size_t(f) * std::size_t(net.stride); }

}  // namespace

bool load(const std::string& path, std::string* error) {
    auto fail = [&](const char* msg) {
        if (error) *error = msg;
        return false;
    };
    FILE* f = std::fopen(path.c_str(), "rb");
    if (!f) return fail("cannot open file");
    char magic[4];
    uint32_t hdr[5];
    float scale;
    bool ok = std::fread(magic, 1, 4, f) == 4 && std::memcmp(magic, "JQN1", 4) == 0 &&
              std::fread(hdr, sizeof(uint32_t), 5, f) == 5 && std::fread(&scale, sizeof(float), 1, f) == 1;
    // hdr: version, features, ft, l1, l2. Version 2: features = kingBuckets * 1440 + 30.
    const int KB = ok && hdr[1] >= uint32_t(NUM_URN_FEATURES) && (hdr[1] - NUM_URN_FEATURES) % NUM_PIECE_FEATURES == 0
                       ? int((hdr[1] - NUM_URN_FEATURES) / NUM_PIECE_FEATURES) : 0;
    const int NF = KB * NUM_PIECE_FEATURES + NUM_URN_FEATURES;
    ok = ok && ((hdr[0] == 1 && KB == 1) || (hdr[0] == 2 && (KB == 3 || KB == 9))) && hdr[2] >= 8 &&
         hdr[2] <= uint32_t(MAX_FT) && hdr[2] % 8 == 0 && hdr[3] >= 1 && hdr[3] <= 256 && hdr[4] >= 1 && hdr[4] <= 256;
    std::vector<float> ftW, ftB, l1W, l1B, l2W, l2B, outW;
    float outB = 0.0f;
    int F = 0, L1 = 0, L2 = 0;
    if (ok) {
        F = int(hdr[2]);
        L1 = int(hdr[3]);
        L2 = int(hdr[4]);
        const std::size_t W = std::size_t(F + 1);
        ok = read_floats(f, ftW, std::size_t(NF) * W) && read_floats(f, ftB, W) &&
             read_floats(f, l1W, std::size_t(L1) * 2 * std::size_t(F)) && read_floats(f, l1B, std::size_t(L1)) &&
             read_floats(f, l2W, std::size_t(L2) * std::size_t(L1)) && read_floats(f, l2B, std::size_t(L2)) &&
             read_floats(f, outW, std::size_t(L2)) && std::fread(&outB, sizeof(float), 1, f) == 1;
        char extra;
        ok = ok && std::fread(&extra, 1, 1, f) == 0;
    }
    std::fclose(f);
    if (!ok) return fail("bad or truncated network file");
    Net n;
    n.ft = F;
    n.l1 = L1;
    n.l2 = L2;
    n.outScale = scale;
    n.outB = outB;
    n.stride = (F + 1 + 7) / 8 * 8;
    const std::size_t S = std::size_t(n.stride);
    n.ftW = alloc(std::size_t(NF) * S);
    for (int r = 0; r < NF; ++r)
        std::memcpy(n.ftW.get() + std::size_t(r) * S, &ftW[std::size_t(r) * std::size_t(F + 1)], sizeof(float) * std::size_t(F + 1));
    n.ftB = alloc(S);
    std::memcpy(n.ftB.get(), ftB.data(), sizeof(float) * std::size_t(F + 1));
    const int L1p = (L1 + 7) / 8 * 8, L2p = (L2 + 7) / 8 * 8;
    n.l1T = alloc(std::size_t(2 * F) * std::size_t(L1p));
    for (int o = 0; o < L1; ++o)
        for (int i = 0; i < 2 * F; ++i)
            n.l1T[std::size_t(i) * std::size_t(L1p) + std::size_t(o)] = l1W[std::size_t(o) * 2 * std::size_t(F) + std::size_t(i)];
    n.l1B = alloc(std::size_t(L1p));
    std::memcpy(n.l1B.get(), l1B.data(), sizeof(float) * std::size_t(L1));
    n.l2T = alloc(std::size_t(L1p) * std::size_t(L2p));
    for (int o = 0; o < L2; ++o)
        for (int i = 0; i < L1; ++i)
            n.l2T[std::size_t(i) * std::size_t(L2p) + std::size_t(o)] = l2W[std::size_t(o) * std::size_t(L1) + std::size_t(i)];
    n.l2B = alloc(std::size_t(L2p));
    std::memcpy(n.l2B.get(), l2B.data(), sizeof(float) * std::size_t(L2));
    n.outW = alloc(std::size_t(L2p));
    std::memcpy(n.outW.get(), outW.data(), sizeof(float) * std::size_t(L2));
    // Quantized copies (AVX2 path requires F % 32 == 0).
#ifdef JQ_AVX2
    n.canQuant = F % 32 == 0;
#endif
    if (n.canQuant) {
        n.qstride = (F + 1 + 15) / 16 * 16;
        const std::size_t QS = std::size_t(n.qstride);
        auto q16 = [](float w) { return int16_t(std::clamp(std::lround(w * QF), -32767L, 32767L)); };
        n.ftWq = alloc_t<int16_t>(std::size_t(NF) * QS);
        for (int r = 0; r < NF; ++r)
            for (int i = 0; i <= F; ++i)
                n.ftWq[std::size_t(r) * QS + std::size_t(i)] = q16(ftW[std::size_t(r) * std::size_t(F + 1) + std::size_t(i)]);
        n.ftBq = alloc_t<int16_t>(QS);
        for (int i = 0; i <= F; ++i) n.ftBq[std::size_t(i)] = q16(ftB[std::size_t(i)]);
        n.l1q = alloc_t<int8_t>(std::size_t(L1) * 2 * std::size_t(F));
        n.l1qInv = alloc(std::size_t((L1 + 7) / 8 * 8));
        for (int o = 0; o < L1; ++o) {
            const float* w = &l1W[std::size_t(o) * 2 * std::size_t(F)];
            float mx = 0.0f;
            for (int i = 0; i < 2 * F; ++i) mx = std::max(mx, std::fabs(w[i]));
            const float sc = mx > 0.0f ? 127.0f / mx : 1.0f;
            n.l1qInv[o] = 1.0f / (float(QA) * sc);
            for (int i = 0; i < 2 * F; ++i)
                n.l1q[std::size_t(o) * 2 * std::size_t(F) + std::size_t(i)] = int8_t(std::clamp(std::lround(w[i] * sc), -127L, 127L));
        }
    }
    net = std::move(n);
    g_kingBuckets = KB;
    g_urnBase = KB * NUM_PIECE_FEATURES;
    g_loaded = true;
    g_quant = g_quantWanted && net.canQuant;
    return true;
}

void set_quantized(bool on) {
    g_quantWanted = on;
    g_quant = on && g_loaded && net.canQuant;
}
bool quantized() { return g_quant; }

void unload() { g_loaded = false; }
void set_flush_denormals() { _mm_setcsr(_mm_getcsr() | 0x8040); }  // FTZ | DAZ for this thread
bool loaded() { return g_loaded; }
int ft_size() { return net.ft + 1; }

namespace {

// dst = src + sum(add rows) - sum(sub rows), over `stride` floats.
void apply_rows(float* dst, const float* src, const float* const* add, int nAdd, const float* const* sub, int nSub) {
    const int S = net.stride;
#ifdef JQ_AVX2
    for (int i = 0; i < S; i += 8) {
        __m256 v = _mm256_load_ps(src + i);
        for (int k = 0; k < nAdd; ++k) v = _mm256_add_ps(v, _mm256_load_ps(add[k] + i));
        for (int k = 0; k < nSub; ++k) v = _mm256_sub_ps(v, _mm256_load_ps(sub[k] + i));
        _mm256_store_ps(dst + i, v);
    }
#else
    for (int i = 0; i < S; ++i) {
        float v = src[i];
        for (int k = 0; k < nAdd; ++k) v += add[k][i];
        for (int k = 0; k < nSub; ++k) v -= sub[k][i];
        dst[i] = v;
    }
#endif
}

}  // namespace

namespace {

inline const int16_t* qrow(int f) { return net.ftWq.get() + std::size_t(f) * std::size_t(net.qstride); }

void apply_rows_q(int16_t* dst, const int16_t* src, const int16_t* const* add, int nAdd, const int16_t* const* sub, int nSub) {
#ifdef JQ_AVX2
    for (int i = 0; i < net.qstride; i += 16) {
        __m256i v = _mm256_load_si256(reinterpret_cast<const __m256i*>(src + i));
        for (int k = 0; k < nAdd; ++k) v = _mm256_add_epi16(v, _mm256_load_si256(reinterpret_cast<const __m256i*>(add[k] + i)));
        for (int k = 0; k < nSub; ++k) v = _mm256_sub_epi16(v, _mm256_load_si256(reinterpret_cast<const __m256i*>(sub[k] + i)));
        _mm256_store_si256(reinterpret_cast<__m256i*>(dst + i), v);
    }
#else
    (void)dst; (void)src; (void)add; (void)nAdd; (void)sub; (void)nSub;
#endif
}

void refresh_q(const Position& pos, Accumulator& acc) {
    for (int pc = 0; pc < 2; ++pc) {
        const Color persp = Color(pc);
        const int kbOff = king_bucket_offset(persp, pos.kingSq[persp]);
        const int16_t* rows[64];
        int n = 0;
        for (int c = 0; c < 2; ++c)
            for (int i = 0; i < pos.pcount[c]; ++i) {
                const int s = pos.plist[c][i];
                rows[n++] = qrow(piece_feature(persp, pos.board[s], s, kbOff));
            }
        for (int c = 0; c < 2; ++c)
            for (int sl = 0; sl < NUM_SLOTS; ++sl)
                for (int j = 1; j <= pos.urn[c][sl]; ++j) rows[n++] = qrow(urn_feature(persp, Color(c), sl, j));
        apply_rows_q(acc.q[pc], net.ftBq.get(), rows, n, nullptr, 0);
    }
}

#ifdef JQ_AVX2
// s += sum of u8(x) * i8(w) over each group of four bytes. Exact either way: x <= 127, so the
// pairwise int16 sums of maddubs cannot saturate.
inline __m256i dot_acc(__m256i s, __m256i x, __m256i w, __m256i ones) {
#ifdef __AVXVNNI__
    (void)ones;
    return _mm256_dpbusd_avx_epi32(s, x, w);
#else
    return _mm256_add_epi32(s, _mm256_madd_epi16(_mm256_maddubs_epi16(x, w), ones));
#endif
}

inline int hsum_epi32(__m256i v) {
    __m128i s = _mm_add_epi32(_mm256_castsi256_si128(v), _mm256_extracti128_si256(v, 1));
    s = _mm_add_epi32(s, _mm_shuffle_epi32(s, 0x4E));
    s = _mm_add_epi32(s, _mm_shuffle_epi32(s, 0xB1));
    return _mm_cvtsi128_si32(s);
}
#endif

Value evaluate_q(const Accumulator& acc, Color stm) {
#ifdef JQ_AVX2
    const int F = net.ft, L1 = net.l1, L2 = net.l2;
    const int L2p = (L2 + 7) / 8 * 8;
    const int16_t* us = acc.q[stm];
    const int16_t* them = acc.q[~stm];
    alignas(64) uint8_t x[2 * MAX_FT];
    const __m256i zero = _mm256_setzero_si256(), qf = _mm256_set1_epi16(QF), one16 = _mm256_set1_epi16(1);
    for (int half = 0; half < 2; ++half) {
        const int16_t* src = half ? them : us;
        for (int i = 0; i < F; i += 32) {
            __m256i a = _mm256_load_si256(reinterpret_cast<const __m256i*>(src + i));
            __m256i b = _mm256_load_si256(reinterpret_cast<const __m256i*>(src + i + 16));
            a = _mm256_srai_epi16(_mm256_add_epi16(_mm256_min_epi16(_mm256_max_epi16(a, zero), qf), one16), 1);
            b = _mm256_srai_epi16(_mm256_add_epi16(_mm256_min_epi16(_mm256_max_epi16(b, zero), qf), one16), 1);
            const __m256i p = _mm256_permute4x64_epi64(_mm256_packus_epi16(a, b), 0xD8);
            _mm256_store_si256(reinterpret_cast<__m256i*>(x + half * F + i), p);
        }
    }
    alignas(64) float h1[256], h2[256];
    const __m256i ones = _mm256_set1_epi16(1);
    int o0 = 0;
    if (L1 % 8 == 0) {
        // Eight outputs per pass: the eight independent sums hide the latency of the multiply-add, and the
        // dequantisation and clamp are done on all eight at once.
        const std::size_t R = 2 * std::size_t(F);
        const __m256 f0 = _mm256_setzero_ps(), f1 = _mm256_set1_ps(1.0f);
        for (; o0 < L1; o0 += 8) {
            const int8_t* w = net.l1q.get() + std::size_t(o0) * R;
            __m256i s0 = zero, s1 = zero, s2 = zero, s3 = zero, s4 = zero, s5 = zero, s6 = zero, s7 = zero;
            for (int i = 0; i < 2 * F; i += 32, w += 32) {
                const __m256i xv = _mm256_load_si256(reinterpret_cast<const __m256i*>(x + i));
                s0 = dot_acc(s0, xv, _mm256_load_si256(reinterpret_cast<const __m256i*>(w)), ones);
                s1 = dot_acc(s1, xv, _mm256_load_si256(reinterpret_cast<const __m256i*>(w + R)), ones);
                s2 = dot_acc(s2, xv, _mm256_load_si256(reinterpret_cast<const __m256i*>(w + 2 * R)), ones);
                s3 = dot_acc(s3, xv, _mm256_load_si256(reinterpret_cast<const __m256i*>(w + 3 * R)), ones);
                s4 = dot_acc(s4, xv, _mm256_load_si256(reinterpret_cast<const __m256i*>(w + 4 * R)), ones);
                s5 = dot_acc(s5, xv, _mm256_load_si256(reinterpret_cast<const __m256i*>(w + 5 * R)), ones);
                s6 = dot_acc(s6, xv, _mm256_load_si256(reinterpret_cast<const __m256i*>(w + 6 * R)), ones);
                s7 = dot_acc(s7, xv, _mm256_load_si256(reinterpret_cast<const __m256i*>(w + 7 * R)), ones);
            }
            const __m256i a = _mm256_hadd_epi32(_mm256_hadd_epi32(s0, s1), _mm256_hadd_epi32(s2, s3));
            const __m256i b = _mm256_hadd_epi32(_mm256_hadd_epi32(s4, s5), _mm256_hadd_epi32(s6, s7));
            const __m256i sums = _mm256_add_epi32(_mm256_permute2x128_si256(a, b, 0x20), _mm256_permute2x128_si256(a, b, 0x31));
            const __m256 v = _mm256_fmadd_ps(_mm256_cvtepi32_ps(sums), _mm256_load_ps(net.l1qInv.get() + o0),
                                             _mm256_load_ps(net.l1B.get() + o0));
            _mm256_store_ps(h1 + o0, _mm256_min_ps(_mm256_max_ps(v, f0), f1));
        }
    } else if (L1 % 4 == 0) {
        // Four outputs per pass share the input loads; one hadd tree reduces all four sums.
        const std::size_t R = 2 * std::size_t(F);
        for (; o0 < L1; o0 += 4) {
            const int8_t* w0 = net.l1q.get() + std::size_t(o0) * R;
            const int8_t* w1 = w0 + R;
            const int8_t* w2 = w1 + R;
            const int8_t* w3 = w2 + R;
            __m256i s0 = _mm256_setzero_si256(), s1 = s0, s2 = s0, s3 = s0;
            for (int i = 0; i < 2 * F; i += 32) {
                const __m256i xv = _mm256_load_si256(reinterpret_cast<const __m256i*>(x + i));
                s0 = dot_acc(s0, xv, _mm256_load_si256(reinterpret_cast<const __m256i*>(w0 + i)), ones);
                s1 = dot_acc(s1, xv, _mm256_load_si256(reinterpret_cast<const __m256i*>(w1 + i)), ones);
                s2 = dot_acc(s2, xv, _mm256_load_si256(reinterpret_cast<const __m256i*>(w2 + i)), ones);
                s3 = dot_acc(s3, xv, _mm256_load_si256(reinterpret_cast<const __m256i*>(w3 + i)), ones);
            }
            s0 = _mm256_hadd_epi32(_mm256_hadd_epi32(s0, s1), _mm256_hadd_epi32(s2, s3));
            const __m128i q = _mm_add_epi32(_mm256_castsi256_si128(s0), _mm256_extracti128_si256(s0, 1));
            alignas(16) int sums[4];
            _mm_store_si128(reinterpret_cast<__m128i*>(sums), q);
            for (int k = 0; k < 4; ++k)
                h1[o0 + k] = std::clamp(float(sums[k]) * net.l1qInv[o0 + k] + net.l1B[o0 + k], 0.0f, 1.0f);
        }
    }
    for (int o = o0; o < L1; ++o) {
        const int8_t* w = net.l1q.get() + std::size_t(o) * 2 * std::size_t(F);
        __m256i s0 = _mm256_setzero_si256(), s1 = _mm256_setzero_si256();
        for (int i = 0; i < 2 * F; i += 64) {
            const __m256i p0 = _mm256_maddubs_epi16(_mm256_load_si256(reinterpret_cast<const __m256i*>(x + i)),
                                                    _mm256_load_si256(reinterpret_cast<const __m256i*>(w + i)));
            const __m256i p1 = _mm256_maddubs_epi16(_mm256_load_si256(reinterpret_cast<const __m256i*>(x + i + 32)),
                                                    _mm256_load_si256(reinterpret_cast<const __m256i*>(w + i + 32)));
            s0 = _mm256_add_epi32(s0, _mm256_madd_epi16(p0, ones));
            s1 = _mm256_add_epi32(s1, _mm256_madd_epi16(p1, ones));
        }
        const int sum = hsum_epi32(_mm256_add_epi32(s0, s1));
        h1[o] = std::clamp(float(sum) * net.l1qInv[o] + net.l1B[o], 0.0f, 1.0f);
    }
    if (L2p == 32) {
        // The four output vectors stay in registers across the inputs (padding biases and weights are zero).
        const float* B = net.l2B.get();
        const float* W = net.l2T.get();
        __m256 a0 = _mm256_load_ps(B), a1 = _mm256_load_ps(B + 8), a2 = _mm256_load_ps(B + 16), a3 = _mm256_load_ps(B + 24);
        for (int i = 0; i < L1; ++i, W += 32) {
            const __m256 xi = _mm256_broadcast_ss(h1 + i);
            a0 = _mm256_fmadd_ps(xi, _mm256_load_ps(W), a0);
            a1 = _mm256_fmadd_ps(xi, _mm256_load_ps(W + 8), a1);
            a2 = _mm256_fmadd_ps(xi, _mm256_load_ps(W + 16), a2);
            a3 = _mm256_fmadd_ps(xi, _mm256_load_ps(W + 24), a3);
        }
        // Output layer on the registers: eight-lane products, one horizontal sum.
        const __m256 f0 = _mm256_setzero_ps(), f1 = _mm256_set1_ps(1.0f);
        const float* OW = net.outW.get();
        __m256 p0 = _mm256_mul_ps(_mm256_min_ps(_mm256_max_ps(a0, f0), f1), _mm256_load_ps(OW));
        __m256 p1 = _mm256_mul_ps(_mm256_min_ps(_mm256_max_ps(a1, f0), f1), _mm256_load_ps(OW + 8));
        p0 = _mm256_fmadd_ps(_mm256_min_ps(_mm256_max_ps(a2, f0), f1), _mm256_load_ps(OW + 16), p0);
        p1 = _mm256_fmadd_ps(_mm256_min_ps(_mm256_max_ps(a3, f0), f1), _mm256_load_ps(OW + 24), p1);
        p0 = _mm256_add_ps(p0, p1);
        __m128 q = _mm_add_ps(_mm256_castps256_ps128(p0), _mm256_extractf128_ps(p0, 1));
        q = _mm_add_ps(q, _mm_movehl_ps(q, q));
        q = _mm_add_ss(q, _mm_shuffle_ps(q, q, 1));
        const float yq = net.outB + _mm_cvtss_f32(q) + 0.5f * float(us[F] - them[F]) / float(QF);
        return Value(std::clamp(yq * net.outScale, -float(VALUE_KNOWN_WIN - 1), float(VALUE_KNOWN_WIN - 1)));
    } else {
        for (int o = 0; o < L2p; ++o) h2[o] = o < L2 ? net.l2B[o] : 0.0f;
        for (int i = 0; i < L1; ++i) {
            const float xi = h1[i];
            const float* w = net.l2T.get() + std::size_t(i) * std::size_t(L2p);
            for (int o = 0; o < L2p; ++o) h2[o] += xi * w[o];
        }
    }
    float y = net.outB;
    for (int o = 0; o < L2; ++o) y += net.outW[o] * std::clamp(h2[o], 0.0f, 1.0f);
    y += 0.5f * float(us[F] - them[F]) / float(QF);
    const float v = y * net.outScale;
    return Value(std::clamp(v, -float(VALUE_KNOWN_WIN - 1), float(VALUE_KNOWN_WIN - 1)));
#else
    (void)acc; (void)stm;
    return VALUE_ZERO;
#endif
}

}  // namespace

void refresh(const Position& pos, Accumulator& acc) {
    if (g_quant) { refresh_q(pos, acc); return; }
    for (int pc = 0; pc < 2; ++pc) {
        const Color persp = Color(pc);
        const int kbOff = king_bucket_offset(persp, pos.kingSq[persp]);
        const float* rows[48];
        int n = 0;
        for (int c = 0; c < 2; ++c)
            for (int i = 0; i < pos.pcount[c]; ++i) {
                const int s = pos.plist[c][i];
                rows[n++] = row(piece_feature(persp, pos.board[s], s, kbOff));
            }
        float* a = acc.v[pc];
        apply_rows(a, net.ftB.get(), rows, n, nullptr, 0);
        n = 0;
        for (int c = 0; c < 2; ++c)
            for (int sl = 0; sl < NUM_SLOTS; ++sl)
                for (int j = 1; j <= pos.urn[c][sl]; ++j) rows[n++] = row(urn_feature(persp, Color(c), sl, j));
        if (n) apply_rows(a, a, rows, n, nullptr, 0);
    }
}

void make_dirty(const Position& pos, Move m, Dirty& d) {
    const int from = from_sq(m), to = to_sq(m);
    const Piece pc = pos.board[from], cap = pos.board[to];
    const Color us = color_of(pc);
    d.nRem = 1;
    d.remP[0] = pc;
    d.remS[0] = int8_t(from);
    if (cap) {
        d.remP[1] = cap;
        d.remS[1] = int8_t(to);
        d.nRem = 2;
    }
    d.nAdd = 1;
    d.addS[0] = int8_t(to);
    d.refresh = -1;
    d.kbOff[RED] = int16_t(king_bucket_offset(RED, pos.kingSq[RED]));
    d.kbOff[BLACK] = int16_t(king_bucket_offset(BLACK, pos.kingSq[BLACK]));
    if (g_kingBuckets > 1 && type_of(pc) == KING && king_bucket_offset(us, to) != d.kbOff[us]) d.refresh = int8_t(us);
    if (type_of(pc) == DARK) {
        const int sl = type_slot(reveal_of(m));
        d.addP[0] = make_piece(us, reveal_of(m));
        d.urnOwner = int8_t(us);
        d.urnSlot = int8_t(sl);
        d.urnJ = int8_t(pos.urn[us][sl]);
    } else {
        d.addP[0] = pc;
        d.urnOwner = -1;
    }
}

void update(const Accumulator& prev, Accumulator& next, const Dirty& d) {
    if (g_quant) {
        for (int pc = 0; pc < 2; ++pc) {
            const Color persp = Color(pc);
            const int16_t* add[1];
            const int16_t* sub[3];
            int nAdd = 0, nSub = 0;
            for (int i = 0; i < d.nRem; ++i) sub[nSub++] = qrow(piece_feature(persp, d.remP[i], d.remS[i], d.kbOff[pc]));
            for (int i = 0; i < d.nAdd; ++i) add[nAdd++] = qrow(piece_feature(persp, d.addP[i], d.addS[i], d.kbOff[pc]));
            if (d.urnOwner >= 0) sub[nSub++] = qrow(urn_feature(persp, Color(d.urnOwner), d.urnSlot, d.urnJ));
            apply_rows_q(next.q[pc], prev.q[pc], add, nAdd, sub, nSub);
        }
        return;
    }
    for (int pc = 0; pc < 2; ++pc) {
        const Color persp = Color(pc);
        const float* add[1];
        const float* sub[3];
        int nAdd = 0, nSub = 0;
        for (int i = 0; i < d.nRem; ++i) sub[nSub++] = row(piece_feature(persp, d.remP[i], d.remS[i], d.kbOff[pc]));
        for (int i = 0; i < d.nAdd; ++i) add[nAdd++] = row(piece_feature(persp, d.addP[i], d.addS[i], d.kbOff[pc]));
        if (d.urnOwner >= 0) sub[nSub++] = row(urn_feature(persp, Color(d.urnOwner), d.urnSlot, d.urnJ));
        apply_rows(next.v[pc], prev.v[pc], add, nAdd, sub, nSub);
    }
}

Value evaluate(const Accumulator& acc, Color stm) {
    if (g_quant) return evaluate_q(acc, stm);
    const int F = net.ft, L1 = net.l1, L2 = net.l2;
    const int L1p = (L1 + 7) / 8 * 8, L2p = (L2 + 7) / 8 * 8;
    const float* us = acc.v[stm];
    const float* them = acc.v[~stm];
    alignas(64) float x[2 * MAX_FT];
    alignas(64) float h1[256], h2[256];
#ifdef JQ_AVX2
    const __m256 zero = _mm256_setzero_ps(), one = _mm256_set1_ps(1.0f);
    for (int i = 0; i < F; i += 8) {
        _mm256_store_ps(x + i, _mm256_min_ps(_mm256_max_ps(_mm256_load_ps(us + i), zero), one));
        _mm256_store_ps(x + F + i, _mm256_min_ps(_mm256_max_ps(_mm256_load_ps(them + i), zero), one));
    }
    if (L1p == 16) {
        // Four independent accumulator pairs hide FMA latency.
        __m256 a0 = _mm256_load_ps(net.l1B.get()), b0 = _mm256_load_ps(net.l1B.get() + 8);
        __m256 a1 = zero, b1 = zero, a2 = zero, b2 = zero, a3 = zero, b3 = zero;
        const float* W = net.l1T.get();
        for (int i = 0; i < 2 * F; i += 4) {
            const float* w = W + std::size_t(i) * 16;
            __m256 x0 = _mm256_broadcast_ss(x + i), x1 = _mm256_broadcast_ss(x + i + 1);
            __m256 x2 = _mm256_broadcast_ss(x + i + 2), x3 = _mm256_broadcast_ss(x + i + 3);
            a0 = _mm256_fmadd_ps(x0, _mm256_load_ps(w), a0);
            b0 = _mm256_fmadd_ps(x0, _mm256_load_ps(w + 8), b0);
            a1 = _mm256_fmadd_ps(x1, _mm256_load_ps(w + 16), a1);
            b1 = _mm256_fmadd_ps(x1, _mm256_load_ps(w + 24), b1);
            a2 = _mm256_fmadd_ps(x2, _mm256_load_ps(w + 32), a2);
            b2 = _mm256_fmadd_ps(x2, _mm256_load_ps(w + 40), b2);
            a3 = _mm256_fmadd_ps(x3, _mm256_load_ps(w + 48), a3);
            b3 = _mm256_fmadd_ps(x3, _mm256_load_ps(w + 56), b3);
        }
        a0 = _mm256_add_ps(_mm256_add_ps(a0, a1), _mm256_add_ps(a2, a3));
        b0 = _mm256_add_ps(_mm256_add_ps(b0, b1), _mm256_add_ps(b2, b3));
        _mm256_store_ps(h1, _mm256_min_ps(_mm256_max_ps(a0, zero), one));
        _mm256_store_ps(h1 + 8, _mm256_min_ps(_mm256_max_ps(b0, zero), one));
    } else
#else
    for (int i = 0; i < F; ++i) x[i] = std::clamp(us[i], 0.0f, 1.0f);
    for (int i = 0; i < F; ++i) x[F + i] = std::clamp(them[i], 0.0f, 1.0f);
#endif
    {
        for (int o = 0; o < L1; ++o) h1[o] = net.l1B[o];
        for (int i = 0; i < 2 * F; ++i) {
            const float xi = x[i];
            const float* w = net.l1T.get() + std::size_t(i) * std::size_t(L1p);
            for (int o = 0; o < L1; ++o) h1[o] += xi * w[o];
        }
        for (int o = 0; o < L1; ++o) h1[o] = std::clamp(h1[o], 0.0f, 1.0f);
    }
    for (int o = L1; o < L1p; ++o) h1[o] = 0.0f;
    for (int o = 0; o < L2p; ++o) h2[o] = o < L2 ? net.l2B[o] : 0.0f;
    for (int i = 0; i < L1; ++i) {
        const float xi = h1[i];
        const float* w = net.l2T.get() + std::size_t(i) * std::size_t(L2p);
        for (int o = 0; o < L2p; ++o) h2[o] += xi * w[o];
    }
    float y = net.outB;
    for (int o = 0; o < L2; ++o) y += net.outW[o] * std::clamp(h2[o], 0.0f, 1.0f);
    y += 0.5f * (us[F] - them[F]);
    const float v = y * net.outScale;
    return Value(std::clamp(v, -float(VALUE_KNOWN_WIN - 1), float(VALUE_KNOWN_WIN - 1)));
}

Value evaluate(const Position& pos) {
    static thread_local Accumulator acc;
    refresh(pos, acc);
    return evaluate(acc, pos.stm);
}

}  // namespace jq::nnue
