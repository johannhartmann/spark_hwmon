/* SPDX-License-Identifier: GPL-2.0 */
/* Host ACPI fixtures exercising the production helpers, without loading a module. */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ACPI_TYPE_INTEGER 1
#define ACPI_TYPE_STRING 2
#define ACPI_TYPE_PACKAGE 4
#define ACPI_TYPE_THERMAL 13
#define ACPI_FAILURE(s) ((s) != 0)
#define ACPI_FREE(p) free(p)
#define BIT(n) (1UL << (n))
#define GENMASK(h, l) (((1UL << ((h) + 1)) - 1) & ~((1UL << (l)) - 1))
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define U32_MAX UINT32_MAX

typedef void *acpi_handle;
typedef char *acpi_string;
typedef unsigned int acpi_object_type;
union acpi_object {
    unsigned int type;
    struct { unsigned int type; uint64_t value; } integer;
    struct { unsigned int type; char *pointer; } string;
    struct { unsigned int type, count; union acpi_object *elements; } package;
};

static int mtel_dsm_guid;
static bool functions_available;
static int resource_index;
static union acpi_object *maps[16];
static bool zone_present, tmp_present, crt_present;
static acpi_object_type zone_type;
static unsigned long long critical;
static int zone;

static bool acpi_check_dsm(acpi_handle h, const int *g, int rev, unsigned long mask)
{
    (void)h; (void)g;
    return rev == 0 && mask == (BIT(1) | BIT(2)) && functions_available;
}
static int spbm_dsm_find_resource(acpi_handle h, const char *name)
{
    (void)h;
    return strcmp(name, "SPBM") ? -1 : resource_index;
}
static union acpi_object *acpi_evaluate_dsm(acpi_handle h, const int *g, int rev,
                                         int function, union acpi_object *args)
{
    union acpi_object *copy, *map;
    (void)h; (void)g; (void)rev;
    if (function != 2 || args->package.count != 1)
        return NULL;
    map = maps[args->package.elements[0].integer.value];
    if (!map)
        return NULL;
    copy = malloc(sizeof(*copy));
    if (!copy)
        abort();
    *copy = *map;
    return copy;
}
static int acpi_get_handle(acpi_handle h, acpi_string path, acpi_handle *out)
{
    (void)h; (void)path;
    *out = &zone;
    return zone_present ? 0 : -1;
}
static int acpi_get_type(acpi_handle h, acpi_object_type *type)
{
    (void)h;
    *type = zone_type;
    return 0;
}
static bool acpi_has_method(acpi_handle h, const char *method)
{
    (void)h;
    return !strcmp(method, "_TMP") && tmp_present;
}
static int acpi_evaluate_integer(acpi_handle h, const char *method, void *args,
                                 unsigned long long *out)
{
    (void)h; (void)args;
    *out = critical;
    return !strcmp(method, "_CRT") && crt_present ? 0 : -1;
}

#include "../n1x-acpi.h"

#define CHECK(test) do { if (!(test)) { \
    fprintf(stderr, "FAIL at line %d: %s\n", __LINE__, #test); return 1; \
} } while (0)
#define NAME(s) { .string = { ACPI_TYPE_STRING, (s) } }
#define OFFSET(n) { .integer = { ACPI_TYPE_INTEGER, (n) } }

int main(void)
{
    union acpi_object fields[] = {
        NAME("CFL"), OFFSET(0x5ac00), NAME("CPL"), OFFSET(0x5a400),
        NAME("CBL"), OFFSET(0x5a600), NAME("CCI"), OFFSET(0x5c404),
        NAME("CPI"), OFFSET(0x5b400),
    };
    union acpi_object valid = { .package = {
        ACPI_TYPE_PACKAGE, ARRAY_SIZE(fields), fields,
    } };
    union acpi_object scalar = OFFSET(0);

    functions_available = true;
    resource_index = 0;
    maps[0] = &valid;
    CHECK(n1x_supported_schema(NULL));
    resource_index = 1; /* Resource index need not equal function-2 sub-index. */
    CHECK(n1x_supported_schema(NULL));
    maps[0] = &scalar;
    maps[7] = &valid;
    CHECK(n1x_supported_schema(NULL));
    maps[7] = NULL;
    CHECK(!n1x_supported_schema(NULL));
    maps[0] = &valid;
    functions_available = false;
    CHECK(!n1x_supported_schema(NULL));
    functions_available = true;
    resource_index = -1;
    CHECK(!n1x_supported_schema(NULL));
    resource_index = 0;

    valid.package.count--;
    CHECK(!n1x_supported_schema(NULL)); /* Odd package. */
    valid.package.count--;
    CHECK(!n1x_supported_schema(NULL)); /* Missing required key. */
    valid.package.count += 2;
    fields[1].type = ACPI_TYPE_STRING;
    CHECK(!n1x_supported_schema(NULL));
    fields[1].type = ACPI_TYPE_INTEGER;
    fields[1].integer.value = 3;
    CHECK(!n1x_supported_schema(NULL)); /* Unaligned offset. */
    fields[1].integer.value = UINT64_C(0x100000000);
    CHECK(!n1x_supported_schema(NULL)); /* Offset overflow. */
    fields[1].integer.value = 0x5ac00;
    fields[2].string.pointer = "CFL";
    CHECK(!n1x_supported_schema(NULL)); /* Duplicate required key. */
    fields[2].string.pointer = "CPL";
    CHECK(n1x_supported_schema(NULL));

    zone_present = tmp_present = crt_present = true;
    zone_type = ACPI_TYPE_THERMAL;
    critical = 0x7fffffff;
    CHECK(n1x_find_sensor("test", false, false) == &zone);
    CHECK(n1x_find_sensor("test", true, false) == NULL); /* Sentinel is not units. */
    CHECK(n1x_find_sensor("test", true, true) == &zone);
    critical = 3732;
    CHECK(n1x_find_sensor("test", true, true) == NULL);
    CHECK(n1x_find_sensor("test", false, false) == &zone);
    critical = 0x7fffffff;
    crt_present = false;
    CHECK(n1x_find_sensor("test", true, true) == NULL);
    crt_present = true;
    tmp_present = false;
    CHECK(n1x_find_sensor("test", false, false) == NULL);
    tmp_present = true;
    zone_type = ACPI_TYPE_INTEGER;
    CHECK(n1x_find_sensor("test", false, false) == NULL);
    zone_type = ACPI_TYPE_THERMAL;
    zone_present = false;
    CHECK(n1x_find_sensor("test", false, false) == NULL);
    puts("PASS: production ACPI helpers accept/reject firmware fixtures correctly");
    return 0;
}
