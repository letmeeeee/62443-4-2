/* Native Linux launcher for an appended device_deploy Python zipapp.
 * The device's installed Python is intentional: the existing app scripts use it too.
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    char executable[PATH_MAX];
    ssize_t length = readlink("/proc/self/exe", executable, sizeof(executable) - 1);
    if (length < 0 || (size_t)length >= sizeof(executable) - 1) {
        fprintf(stderr, "Cannot locate device deploy executable: %s\n", strerror(errno));
        return 1;
    }
    executable[length] = '\0';
    const char *python = getenv("LC400_PYTHON");
    if (python && (*python != '/' || access(python, X_OK) != 0)) {
        fprintf(stderr, "LC400_PYTHON must name an executable Python 3 using an absolute path.\n");
        return 1;
    }
    if (!python) {
        const char *candidates[] = {"/home/zlg/myenv/bin/python3", "/usr/bin/python3", "/usr/local/bin/python3"};
        for (unsigned i = 0; i < sizeof(candidates) / sizeof(candidates[0]); ++i) {
            if (access(candidates[i], X_OK) == 0) { python = candidates[i]; break; }
        }
    }
    if (!python) {
        fprintf(stderr, "Python 3.8+ is required on the device; set LC400_PYTHON to its absolute path.\n");
        return 1;
    }
    char **arguments = calloc((size_t)argc + 2, sizeof(char *));
    if (!arguments) { perror("calloc"); return 1; }
    arguments[0] = (char *)python;
    arguments[1] = executable;
    for (int i = 1; i < argc; ++i) arguments[i + 1] = argv[i];
    execv(python, arguments);
    fprintf(stderr, "Cannot start device Python: %s\n", strerror(errno));
    free(arguments);
    return 1;
}
