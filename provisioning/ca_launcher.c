/* Linux CA desktop launcher for a bundled Python runtime, located beside this ELF. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#ifndef LC_PYTHON_SITE
#error LC_PYTHON_SITE must identify the bundled site-packages directory
#endif

#ifndef LC_APP_SCRIPT
#define LC_APP_SCRIPT "app/ca_manager.py"
#endif

static int environment_path(const char *name, const char *base, const char *suffix) {
    char path[PATH_MAX];
    int n = snprintf(path, sizeof(path), "%s/%s", base, suffix);
    return n >= 0 && (size_t)n < sizeof(path) && setenv(name, path, 1) == 0;
}
int main(int argc, char **argv) {
    char base[PATH_MAX], python[PATH_MAX], script[PATH_MAX];
    ssize_t n = readlink("/proc/self/exe", base, sizeof(base)-1);
    if (n < 0 || (size_t)n >= sizeof(base)-1) { perror("locate desktop launcher"); return 1; }
    base[n] = '\0';
    char *separator = strrchr(base, '/');
    if (!separator) return 1;
    *separator = '\0';
    int a = snprintf(python, sizeof(python), "%s/runtime/bin/python3", base);
    int b = snprintf(script, sizeof(script), "%s/%s", base, LC_APP_SCRIPT);
    if (a < 0 || b < 0 || (size_t)a >= sizeof(python) || (size_t)b >= sizeof(script)) return 1;
    if (!environment_path("PYTHONHOME",base,"runtime") ||
        !environment_path("LD_LIBRARY_PATH",base,"runtime/lib") ||
        !environment_path("PYTHONPATH",base,LC_PYTHON_SITE) ||
        !environment_path("TCL_LIBRARY",base,"runtime/share/tcl") ||
        !environment_path("TK_LIBRARY",base,"runtime/share/tk")) {
        perror("configure desktop runtime"); return 1;
    }
    setenv("PYTHONNOUSERSITE", "1", 1);
    setenv("PYTHONDONTWRITEBYTECODE", "1", 1);
    char **arguments = calloc((size_t)argc+2, sizeof(char *));
    if (!arguments) { perror("calloc"); return 1; }
    arguments[0] = python; arguments[1] = script;
    for (int i=1; i<argc; ++i) arguments[i+1] = argv[i];
    execv(python, arguments);
    fprintf(stderr,"Cannot start bundled desktop runtime: %s\nKeep runtime/ and app/ beside this executable.\n",strerror(errno));
    free(arguments); return 1;
}
