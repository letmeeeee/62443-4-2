#ifndef __RPCH_COMMON_H__
#define __RPCH_COMMON_H__

#include <assert.h>
#include <dirent.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
#include <fcntl.h>
#include <string.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/ioctl.h>
#include <sys/time.h>
// #include <linux/rpmsg.h>
#include <pthread.h>

#ifndef _RPMSG_H_
#include <linux/ioctl.h>
#include <linux/types.h>

#define RPMSG_ADDR_ANY		0xFFFFFFFF

/**
 * struct rpmsg_endpoint_info - endpoint info representation
 * @name: name of service
 * @src: local address. To set to RPMSG_ADDR_ANY if not used.
 * @dst: destination address. To set to RPMSG_ADDR_ANY if not used.
 */
struct rpmsg_endpoint_info {
	char name[32];
	__u32 src;
	__u32 dst;
};

/**
 * Instantiate a new rmpsg char device endpoint.
 */
#define RPMSG_CREATE_EPT_IOCTL	_IOW(0xb5, 0x1, struct rpmsg_endpoint_info)

/**
 * Destroy a rpmsg char device endpoint created by the RPMSG_CREATE_EPT_IOCTL.
 */
#define RPMSG_DESTROY_EPT_IOCTL	_IO(0xb5, 0x2)

/**
 * Instantiate a new local rpmsg service device.
 */
#define RPMSG_CREATE_DEV_IOCTL	_IOW(0xb5, 0x3, struct rpmsg_endpoint_info)

/**
 * Release a local rpmsg device.
 */
#define RPMSG_RELEASE_DEV_IOCTL	_IOW(0xb5, 0x4, struct rpmsg_endpoint_info)

/**
 * Get the flow control state of the remote rpmsg char device.
 */
#define RPMSG_GET_OUTGOING_FLOWCONTROL _IOR(0xb5, 0x5, int)

/**
 * Set the flow control state of the local rpmsg char device.
 */
#define RPMSG_SET_INCOMING_FLOWCONTROL _IOR(0xb5, 0x6, int)
#endif

#define RPMSG_HEADER_LEN 16
#define MAX_RPMSG_BUFF_SIZE (508 - RPMSG_HEADER_LEN)

// User-defined data format
struct _sample_payload {
    uint32_t cmd;
    uint32_t size;
    uint32_t arg1;
    uint32_t arg2;
    char data[];
}__attribute__((__packed__));

#define PAYLOAD_SIZE                (MAX_RPMSG_BUFF_SIZE - sizeof(struct _sample_payload))

#define RPMSG_BUS_SYS "/sys/bus/rpmsg"

#ifndef RPMSG_GETPROP_EPT_IOCTL
/*****************************************************************************
 ** \brief Extended definition in libc kernel header uapi/linux/rpmsgh.h
 *****************************************************************************/
struct rpmsg_endpoint_property {
    char name[32];
    __u32 src;
    __u32 dst;
    __u32 mtu;
};

#define RPMSG_GETPROP_EPT_IOCTL	_IOR(0xb5, 0x3, struct rpmsg_endpoint_property)
#endif

/*****************************************************************************
 ** \brief Extended definition in libc kernel header uapi/linux/rpmsg_socket.h
 **  http://gerrit.semidrive.net:8081/#/c/android/kernel/common/+/1263/8/include/uapi/linux/rpmsg_socket.h
 *****************************************************************************/
#include <sys/socket.h>
#include <linux/types.h>
#include <linux/socket.h>

#ifndef AF_RPMSG
#define AF_RPMSG	44
#define PF_RPMSG	AF_RPMSG
#endif

struct sockaddr_rpmsg {
    sa_family_t family;
    __u32 vproc_id;
    __u32 addr;
};

/*****************************************************************************
 ** \brief Extended definition from DCF uapi
 **   source/linux/drivers/soc/semidrive/uapi/dcf-ioctl.h
 *****************************************************************************/
struct dcf_ioc_setproperty {
    __u32 property_id;
    __u32 property_value;
    __u32 reserved1;
    __u32 reserved2;
};

#define DCF_IOC_MAGIC       'D'
#define DCF_IOC_SET_PROPERTY    _IOWR(DCF_IOC_MAGIC, 2,\
                    struct dcf_ioc_setproperty)

#define DCF_IOC_GET_PROPERTY    _IOWR(DCF_IOC_MAGIC, 3,\
                    struct dcf_ioc_setproperty)

/*****************************************************************************
 ** \brief message header for rpmsg channel ping latency measurement
 **  keep the structure be aligned between domains.
 *****************************************************************************/
struct rpmsg_ping_hdr {
    uint32_t magic    : 8;
    uint32_t rsvd1    : 8;
    uint32_t data_len : 16;
    uint32_t rsvd2;
    uint32_t seq;
    uint32_t time[4];
    char    data[];
} __attribute__((__packed__));

int rpmsg_create_ept(int rpfd, struct rpmsg_endpoint_info *eptinfo);
char *get_rpmsg_ept_dev_name(const char *rpmsg_char_name,
                                    const char *ept_name,
                                    char *ept_dev_name);

/*****************************************************************************
 ** \brief Get rpmsg endpoint property
 ** \param [in] fd          file descriptor for the rpmsg endpoint node.
 ** \param [in] ept_prop    endpoint property structure
 ** \return 0 for success or negative for any failure
 *****************************************************************************/
int get_rpmsg_ept_info(int fd, struct rpmsg_endpoint_property *ept_prop);

int bind_rpmsg_chrdev(const char *rpmsg_dev_name);
int unbind_rpmsg_chrdev(const char *rpmsg_dev_name);
int get_rpmsg_chrdev_fd(const char *rpmsg_dev_name,
                               char *rpmsg_ctrl_name);
int rpch_check_path(char *rpmsg_dev);
int rpch_create(char *ept_dev_path, char *rpmsg_dev, struct rpmsg_endpoint_info eptinfo);
int rpch_sample_server(int fd);
int rpch_sample_client(int fd);

/*****************************************************************************
 ** \brief Set/Get A property value from remote domain.
 ** \param [in] dom     remote processor domain (alway 0 reserved for future)
 ** \param [in] id      property id
 ** \param [in] value   property value, or returned pointer
 ** \return 0 for success or negative for any failure
 *****************************************************************************/
int semidrive_set_domain_property(int dom, uint32_t id, uint32_t value);
int semidrive_get_domain_property(int dom, uint32_t id, uint32_t *value);

#endif
