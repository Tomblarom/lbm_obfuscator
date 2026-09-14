/*
 * Native LispBM test host. No VESC transport or hardware code is linked.
 * Initialization follows LispBM tests/test_lisp_code_cps.c and VESC lispif.c.
 * Copyright 2018, 2020, 2023 Joel Svensson <svenssonjoel@yahoo.se>
 * Test host adaptations, 2026: staged execution, exact import buffers and traces.
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#define _GNU_SOURCE
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#include "lispbm.h"
#include "lbm_image.h"
#include "extensions/array_extensions.h"
#include "extensions/lbm_dyn_lib.h"
#include "extensions/math_extensions.h"
#include "extensions/string_extensions.h"
#include "extensions/runtime_extensions.h"
#include "extensions/mutex_extensions.h"

#define HEAP_CELLS (128 * 1024)
#define IMAGE_BYTES (4 * 1024 * 1024)
#define EXT_COUNT 512
#define TRACE_BYTES 65536

static lbm_cons_t heap[HEAP_CELLS] __attribute__((aligned(8)));
static lbm_uint memory[LBM_MEMORY_SIZE_1M] __attribute__((aligned(8)));
static lbm_uint bitmap[LBM_MEMORY_BITMAP_SIZE_1M];
static lbm_extension_t extensions[EXT_COUNT];
static uint32_t *image;
static atomic_bool stage_done;
static atomic_bool failed;
static lbm_cid stage_cid = -1;
static char print_buffer[TRACE_BYTES];

static void die(const char *message) {
    fprintf(stderr, "LispBM test host: %s\n", message);
    exit(2);
}

/* Linux HAL clock for the unmodified evaluator (no timestamp worker needed). */
uint32_t lbm_timestamp(void) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) die("clock_gettime failed");
    return (uint32_t)((uint64_t)now.tv_sec * 1000000u + (uint64_t)now.tv_nsec / 1000u);
}

static void sleep_us(uint32_t us) {
    struct timespec delay = {(time_t)(us / 1000000u), (long)(us % 1000000u) * 1000L};
    while (nanosleep(&delay, &delay) != 0 && errno == EINTR) {}
}

static bool image_write(uint32_t word, int32_t index, bool const_heap) {
    (void)const_heap;
    if (index < 0 || (uint32_t)index >= IMAGE_BYTES / sizeof(uint32_t)) return false;
    if (image[index] != 0xffffffffu && image[index] != word) return false;
    image[index] = word;
    return true;
}

static void critical_error(void) { die("LispBM critical error"); }

static void print_value(lbm_value value) {
    memset(print_buffer, 0, sizeof(print_buffer));
    if (!lbm_print_value(print_buffer, sizeof(print_buffer), value)) die("trace exceeds print buffer");
    fputs(print_buffer, stdout);
}

static lbm_value trace(const char *label, lbm_value *args, lbm_uint count) {
    fputs(label, stdout);
    for (lbm_uint i = 0; i < count; ++i) {
        fputc(' ', stdout);
        print_value(args[i]);
    }
    fputc('\n', stdout);
    fflush(stdout);
    return ENC_SYM_TRUE;
}

static lbm_value ext_emit(lbm_value *args, lbm_uint count) { return trace("TRACE", args, count); }
static lbm_value ext_print(lbm_value *args, lbm_uint count) { return trace("PRINT", args, count); }
static lbm_value ext_puts(lbm_value *args, lbm_uint count) { return trace("PUTS", args, count); }
static lbm_value ext_handler(lbm_value *args, lbm_uint count) {
    (void)args;
    if (count != 0) return ENC_SYM_EERROR;
    return lbm_enc_i(lbm_get_event_handler_pid());
}

static lbm_value ext_assert(lbm_value *args, lbm_uint count) {
    if (count != 1 || args[0] != ENC_SYM_TRUE) {
        trace("ASSERTION-FAILED", args, count);
        atomic_store(&failed, true);
        lbm_set_error_reason("Test assertion failed");
        return ENC_SYM_EERROR;
    }
    return ENC_SYM_TRUE;
}

static void context_done(eval_context_t *context) {
    if (lbm_is_symbol(context->r)) {
        lbm_uint symbol = lbm_dec_sym(context->r);
        if (symbol >= SYM_RERROR && symbol <= SYM_ERROR_FLASH_HEAP_FULL) {
            atomic_store(&failed, true);
        }
    }
    if (context->id == stage_cid) {
        fputs("RESULT ", stdout);
        print_value(context->r);
        fputc('\n', stdout);
        fflush(stdout);
        atomic_store(&stage_done, true);
    }
}

static void *eval_thread(void *unused) {
    (void)unused;
    lbm_run_eval();
    return NULL;
}

static void pause_eval(void) {
    lbm_pause_eval();
    uint32_t start = lbm_timestamp();
    while (lbm_get_eval_state() != EVAL_CPS_STATE_PAUSED) {
        if ((uint32_t)(lbm_timestamp() - start) > 2000000u) die("pause timeout");
        sleep_us(100);
    }
}

static char *read_file(const char *path, size_t *length) {
    FILE *file = fopen(path, "rb");
    if (!file) die("cannot open local fixture file");
    if (fseek(file, 0, SEEK_END) != 0) die("cannot seek fixture");
    long size = ftell(file);
    if (size < 0 || size > 16 * 1024 * 1024) die("invalid fixture size");
    rewind(file);
    char *data = calloc((size_t)size + 1u, 1u);
    if (!data || fread(data, 1, (size_t)size, file) != (size_t)size) die("cannot read fixture");
    fclose(file);
    *length = (size_t)size;
    return data;
}

static void run_stage(const char *path) {
    pause_eval();
    size_t length;
    char *text = read_file(path, &length);
    if (memchr(text, 0, length)) die("raw NUL in executable source");
    if (length == 0) {
        puts("RESULT nil");
        free(text);
        return;
    }
    lbm_string_channel_state_t channel_state;
    lbm_char_channel_t channel;
    lbm_create_string_char_channel(&channel_state, &channel, text);
    atomic_store(&stage_done, false);
    stage_cid = lbm_load_and_eval_program_incremental(&channel, "test-stage");
    if (stage_cid < 0) die("cannot create evaluator context");
    uint32_t start = lbm_timestamp();
    lbm_continue_eval();
    while (!atomic_load(&stage_done) && !atomic_load(&failed)) {
        if ((uint32_t)(lbm_timestamp() - start) > 10000000u) die("stage execution timeout");
        sleep_us(100);
    }
    pause_eval();
    free(text);
    if (atomic_load(&failed)) die("LispBM evaluation or assertion failed");
}

int main(int argc, char **argv) {
    image = mmap((void *)0xA0000000, IMAGE_BYTES, PROT_READ | PROT_WRITE,
                 MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    if (image == MAP_FAILED) die("cannot allocate local emulated constant heap");
    memset(image, 0xff, IMAGE_BYTES);
    if (!lbm_init(heap, HEAP_CELLS, memory, LBM_MEMORY_SIZE_1M,
                  bitmap, LBM_MEMORY_BITMAP_SIZE_1M, 1024, 1024, extensions, EXT_COUNT)) die("lbm_init failed");
    lbm_image_init(image, IMAGE_BYTES / sizeof(lbm_uint), image_write);
    lbm_image_create("test-test");
    if (!lbm_image_boot()) die("image initialization failed");
    lbm_add_eval_symbols();
    if (!lbm_eval_init_events(32)) die("event initialization failed");
    lbm_array_extensions_init();
    lbm_math_extensions_init();
    lbm_string_extensions_init();
    lbm_runtime_extensions_init();
    lbm_mutex_extensions_init();
    lbm_dyn_lib_init();
    if (!lbm_add_extension("test-emit", ext_emit) || !lbm_add_extension("test-assert", ext_assert)
        || !lbm_add_extension("print", ext_print) || !lbm_add_extension("puts", ext_puts)
        || !lbm_add_extension("test-handler", ext_handler)) die("extension storage full");
    lbm_set_dynamic_load_callback(lbm_dyn_lib_find);
    lbm_set_usleep_callback(sleep_us);
    lbm_set_printf_callback(printf);
    lbm_set_critical_error_callback(critical_error);
    lbm_set_ctx_done_callback(context_done);
    lbm_set_verbose(true);

    pthread_t evaluator;
    if (pthread_create(&evaluator, NULL, eval_thread, NULL) != 0) die("cannot start evaluator");
    pause_eval();

    /* As in lispif.c, bind all exact, constant import buffers before execution. */
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--import") && i + 2 < argc) {
            char *name = argv[++i];
            size_t length;
            char *data = read_file(argv[++i], &length);
            lbm_value value;
            if (!lbm_share_array_const(&value, data, (lbm_uint)length) || !lbm_define(name, value)) die("cannot bind import");
        } else if (!strcmp(argv[i], "--file") && i + 1 < argc) {
            ++i;
        } else {
            die("usage: lispbm-host [--import SYMBOL FILE]... --file FILE [--file FILE]...");
        }
    }
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--import")) i += 2;
        else if (!strcmp(argv[i], "--file")) run_stage(argv[++i]);
    }
    lbm_kill_eval();
    pthread_join(evaluator, NULL);
    return atomic_load(&failed) ? 2 : 0;
}
