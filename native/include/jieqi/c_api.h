#ifndef JIEQI_C_API_H
#define JIEQI_C_API_H
#include <stddef.h>
#include <stdint.h>
#if defined(_WIN32)
# if defined(JIEQI_BUILD_DLL)
#  define JIEQI_API __declspec(dllexport)
# else
#  define JIEQI_API __declspec(dllimport)
# endif
#else
# define JIEQI_API __attribute__((visibility("default")))
#endif
#ifdef __cplusplus
extern "C" {
#endif

/* ABI v4: board = exactly 90 public ASCII cells, rank 0 first; side=0 red/1 black.
 * Errors are caller-owned buffers; game handles are created/freed by this library.
 * No hidden identity is required for move generation or in-check queries. */
enum { JQ_OK = 0, JQ_INVALID = 1, JQ_BUFFER_TOO_SMALL = 2, JQ_INTERNAL = 3 };
JIEQI_API int jq_abi_version(void);
JIEQI_API int jq_legal_moves(const char* board, size_t length, int side,
                             uint16_t* moves, size_t capacity, size_t* count,
                             char* error, size_t error_capacity);
JIEQI_API int jq_in_check(const char* board, size_t length, int side, int* checked,
                          char* error, size_t error_capacity);
/* reveal is uppercase R/N/B/A/C/P for a dark mover, or zero for a bright mover.
 * Output is exactly 90 bytes, not null terminated. No writes on failure. */
JIEQI_API int jq_apply_move(const char* board, size_t length, int side, int from, int to,
                            char reveal, char* output, size_t capacity,
                            char* error, size_t error_capacity);
/* status: 0 ongoing, 1 side-to-move loss, 2 no-capture draw. NOT chase/repetition. */
JIEQI_API int jq_basic_status(const char* board, size_t length, int side,
                              uint32_t no_capture_plies, uint32_t no_capture_limit, int* status,
                              char* error, size_t error_capacity);
JIEQI_API int jq_perft_revealed(const char* board, size_t length, int side, int depth,
                                uint64_t* nodes, char* error, size_t error_capacity);

/* Diagnostic legal replay only; not full-referee terminal adjudication.
 * moves encode from*90+to, reveals are one byte per move (zero when bright).
 * repetition: 0 not repeated, 1 draw, 2 red loses, 3 black loses,
 * 4 chase analysis required. The caller must never turn 4 into a draw.
 * begin/end are relative snapshot indices, perpetual bits: red=1, black=2.
 * No writes to outputs on failure. All output pointers must be non-null. */
JIEQI_API int jq_repetition_replay(const char* board, size_t length, int side, uint32_t idle,
                                  const uint16_t* moves, const char* reveals, size_t move_count,
                                  int* repetition, size_t* begin, size_t* end, int* perpetual_bits,
                                  char* error, size_t error_capacity);

/* Pinned-profile diagnostic threat bits: exactly 90 bytes, values 0 or 1. */
JIEQI_API int jq_chase_targets(const char* board, size_t length, int side, unsigned char* output,
                             size_t capacity, char* error, size_t error_capacity);
/* Strict terminal-aware replay; result 0 ongoing, 1 draw, 2 red loss, 3 black loss.
 * Rejects any continuation after a prior terminal state. No writes on failure. */
JIEQI_API int jq_game_replay(const char* board, size_t length, int side, uint32_t idle,
                            const uint16_t* moves, const char* reveals, size_t move_count,
                            uint32_t no_capture_limit, int* result, char* error, size_t error_capacity);

/* Opaque public-history handles. One thread owns a handle; do not copy/free it
 * yourself. Destroy exactly once (null is permitted). Invalid/dangling non-null
 * handles are outside the C ABI contract. Limits stay fixed for the game. */
typedef struct jq_game jq_game;
JIEQI_API int jq_game_create(const char* board, size_t length, int side, uint32_t idle,
                             uint32_t limit, jq_game** output, char* error, size_t error_capacity);
JIEQI_API void jq_game_destroy(jq_game* game);
JIEQI_API int jq_game_advance(jq_game* game, int from, int to, char reveal,
                              char* error, size_t error_capacity);
/* Snapshot writes no outputs on failure. Board capacity must be at least 90. */
JIEQI_API int jq_game_snapshot(const jq_game* game, char* board, size_t capacity,
                               int* side, uint32_t* idle, size_t* plies, int* result,
                               char* error, size_t error_capacity);

#ifdef __cplusplus
}
#endif
#endif
