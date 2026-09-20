

#ifndef DIO_ZLG_H
#define DIO_ZLG_H

/* Make this header file easier to include in C++ code */
#ifdef __cplusplus
extern "C" {
#endif

int	get_di_state(int port, int *state);

int	set_do_state(int port, int state);

#ifdef __cplusplus
}
#endif

#endif //DIO_ZLG_H
