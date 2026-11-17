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
#include <rpch_common.h>

int rpmsg_create_ept(int rpfd, struct rpmsg_endpoint_info *eptinfo)
{
    int ret;

    ret = ioctl(rpfd, RPMSG_CREATE_EPT_IOCTL, eptinfo);

    if (ret)
        perror("Failed to create endpoint.\n");

    return ret;
}

char *get_rpmsg_ept_dev_name(const char *rpmsg_char_name,
                                    const char *ept_name,
                                    char *ept_dev_name)
{
    char sys_rpmsg_ept_name_path[64];
    char svc_name[64];
    char *sys_rpmsg_path = "/sys/class/rpmsg";
    FILE *fp;
    int i;
    int ept_name_len;

    for (i = 0; i < 128; i++) {
        sprintf(sys_rpmsg_ept_name_path, "%s/%s/rpmsg%d/name",
                sys_rpmsg_path, rpmsg_char_name, i);
        // printf("checking %s\n", sys_rpmsg_ept_name_path);

        if (access(sys_rpmsg_ept_name_path, F_OK) < 0)
            continue;

        fp = fopen(sys_rpmsg_ept_name_path, "r");

        if (!fp) {
            printf("failed to open %s\n", sys_rpmsg_ept_name_path);
            break;
        }

        fgets(svc_name, sizeof(svc_name), fp);
        fclose(fp);
        // printf("svc_name: %s\n", svc_name);
        ept_name_len = strlen(ept_name);

        if (ept_name_len > sizeof(svc_name))
            ept_name_len = sizeof(svc_name);

        if (!strncmp(svc_name, ept_name, ept_name_len)) {
            sprintf(ept_dev_name, "rpmsg%d", i);
            return ept_dev_name;
        }
    }

    printf("Not able to RPMsg endpoint file for %s:%s.\n",
           rpmsg_char_name, ept_name);
    return NULL;
}

int get_rpmsg_ept_info(int fd, struct rpmsg_endpoint_property *ept_prop)
{
    int ret;

    memset(ept_prop, 0, sizeof(*ept_prop));
    ret = ioctl(fd, RPMSG_GETPROP_EPT_IOCTL, ept_prop);
    if (ret < 0)
        perror("Failed to get endpoint info, not support\n");

    return ret;
}

int bind_rpmsg_chrdev(const char *rpmsg_dev_name)
{
    char fpath[256];
    char *rpmsg_chdrv = "rpmsg_chrdev";
    int fd;
    int ret;


    /* rpmsg dev overrides path */
    sprintf(fpath, "%s/devices/%s/driver_override",
            RPMSG_BUS_SYS, rpmsg_dev_name);
    fd = open(fpath, O_WRONLY);

    if (fd < 0) {
        fprintf(stderr, "Failed to open %s, %s\n",
                fpath, strerror(errno));
        return -EINVAL;
    }

    ret = write(fd, rpmsg_chdrv, strlen(rpmsg_chdrv) + 1);

    if (ret < 0) {
        fprintf(stderr, "Failed to write %s to %s, %s\n",
                rpmsg_chdrv, fpath, strerror(errno));
        return -EINVAL;
    }

    close(fd);

    /* bind the rpmsg device to rpmsg char driver */
    sprintf(fpath, "%s/drivers/%s/bind", RPMSG_BUS_SYS, rpmsg_chdrv);
    fd = open(fpath, O_WRONLY);

    if (fd < 0) {
        fprintf(stderr, "Failed to open %s, %s\n",
                fpath, strerror(errno));
        return -EINVAL;
    }

    ret = write(fd, rpmsg_dev_name, strlen(rpmsg_dev_name) + 1);

    if (ret < 0) {
        fprintf(stderr, "Failed to write %s to %s, %s\n",
                rpmsg_dev_name, fpath, strerror(errno));
        fprintf(stderr,
                "If it's already bind, please unbind with below command, then try again\n");
        fprintf(stderr, "echo %s > %s/drivers/%s/unbind\n", rpmsg_dev_name,
                RPMSG_BUS_SYS, rpmsg_chdrv);
        return -EINVAL;
    }

    close(fd);
    return 0;
}

int unbind_rpmsg_chrdev(const char *rpmsg_dev_name)
{
    char fpath[256];
    char *rpmsg_chdrv = "rpmsg_chrdev";
    int fd;
    int ret;

    /* unbind the rpmsg device to rpmsg char driver */
    sprintf(fpath, "%s/drivers/%s/unbind", RPMSG_BUS_SYS, rpmsg_chdrv);
    fd = open(fpath, O_WRONLY);

    if (fd < 0) {
        fprintf(stderr, "Failed to open %s, %s\n",
                fpath, strerror(errno));
        return -EINVAL;
    }

    ret = write(fd, rpmsg_dev_name, strlen(rpmsg_dev_name) + 1);

    if (ret < 0) {
        fprintf(stderr, "Failed to write %s to %s, %s\n",
                rpmsg_dev_name, fpath, strerror(errno));
        return -EINVAL;
    }

    close(fd);
    return 0;
}

int get_rpmsg_chrdev_fd(const char *rpmsg_dev_name,
                               char *rpmsg_ctrl_name)
{
    char dpath[256];
    char fpath[256];
    int path_len = 0;
    char *rpmsg_ctrl_prefix = "rpmsg_ctrl";
    DIR *dir;
    struct dirent *ent;
    int fd;

    sprintf(dpath, "%s/devices/%s/rpmsg", RPMSG_BUS_SYS, rpmsg_dev_name);
    dir = opendir(dpath);

    if (dir == NULL) {
        fprintf(stderr, "Failed to open dir %s\n", dpath);
        return -EINVAL;
    }

    while ((ent = readdir(dir)) != NULL) {
        if (!strncmp(ent->d_name, rpmsg_ctrl_prefix,
                     strlen(rpmsg_ctrl_prefix))) {
            // printf("Opening file %s.\n", ent->d_name);
            path_len = snprintf(fpath, sizeof(fpath),  "/dev/%s", ent->d_name);

            if (path_len <= 0)
                continue;

            fd = open(fpath, O_RDWR | O_NONBLOCK);

            if (fd < 0) {
                fprintf(stderr,
                        "Failed to open rpmsg char dev %s,%s\n",
                        fpath, strerror(errno));
                return fd;
            }

            sprintf(rpmsg_ctrl_name, "%s", ent->d_name);
            return fd;
        }
    }

    fprintf(stderr, "No rpmsg char dev file is found\n");
    return -EINVAL;
}

int rpch_check_path(char *rpmsg_dev)
{
    char fpath[256];
    sprintf(fpath, "%s/devices/%s", RPMSG_BUS_SYS, rpmsg_dev);
    if (access(fpath, F_OK)) {
        return -EINVAL;
    }

    return 0;
}

int rpch_create(char *ept_dev_path, char *rpmsg_dev, struct rpmsg_endpoint_info eptinfo)
{
    char ept_dev_name[16];
    char rpmsg_char_name[16];
    int charfd;
    int ret;

    ret = bind_rpmsg_chrdev(rpmsg_dev);

    if (ret < 0)
        return -EINVAL;

    charfd = get_rpmsg_chrdev_fd(rpmsg_dev, rpmsg_char_name);

    if (charfd < 0)
        return charfd;

    /* Create endpoint from rpmsg char driver */
    ret = rpmsg_create_ept(charfd, &eptinfo);

    if (ret) {
        printf("failed to create RPMsg endpoint.\n");
        return -EINVAL;
    }

    if (!get_rpmsg_ept_dev_name(rpmsg_char_name, eptinfo.name,
                                    ept_dev_name))
        return -EINVAL;

    sprintf(ept_dev_path, "/dev/%s", ept_dev_name);

    return charfd;
}

int rpch_sample_client(int fd)
{
    int bytes_sent;
    int bytes_rcvd;
    char tx_buf[MAX_RPMSG_BUFF_SIZE] = {0,};
    char rx_buf[MAX_RPMSG_BUFF_SIZE] = {0,};
    int len = MAX_RPMSG_BUFF_SIZE;

    char message[] = "hello remote processor";
    memcpy(tx_buf, message, sizeof(message));

    bytes_sent = write(fd, tx_buf, len);
    if (bytes_sent <= 0) {
        printf("Error sending data %d\n", bytes_sent);
    }
    else {
        printf("write ok\n");
    }

    bytes_rcvd = read(fd, rx_buf, len);
    if (bytes_rcvd < len) {
        printf("Error receiving data %d\n", bytes_rcvd);
    }
    else {
        printf("the message is: %s\n", rx_buf);
    }

    return 0;
}

int rpch_sample_server(int fd)
{
    int bytes_sent;
    int bytes_rcvd;
    char tx_buf[MAX_RPMSG_BUFF_SIZE] = {0,};
    char rx_buf[MAX_RPMSG_BUFF_SIZE] = {0,};
    int len = MAX_RPMSG_BUFF_SIZE;

    char message[] = "receive the request";
    memcpy(tx_buf, message, sizeof(message));

    bytes_rcvd = read(fd, rx_buf, len);
    if (bytes_rcvd < len) {
        printf("Error sending data %d\n", bytes_rcvd);
    }
    else {
        printf("the message is: %s\n", rx_buf);
    }

    bytes_sent = write(fd, tx_buf, len);
    if (bytes_sent <= 0) {
        printf("Error receiving data %d\n", bytes_sent);
    }
    else {
        printf("write ok\n");
    }

    return 0;
}

int semidrive_set_domain_property(int dom, uint32_t id, uint32_t value)
{
    struct dcf_ioc_setproperty setprop;
    int prop_fd;
    int ret;

    prop_fd = open("/dev/property", O_RDWR);
    if (prop_fd < 0) {
        perror("Failed to open property device.");
        return prop_fd;
    }

    setprop.property_id = id;
    setprop.property_value = value;
    ret = ioctl(prop_fd, DCF_IOC_SET_PROPERTY, &setprop);
    if (ret)
        perror("Failed to create endpoint.\n");

    close(prop_fd);

    return ret;
}

int semidrive_get_domain_property(int dom, uint32_t id, uint32_t *value)
{
    struct dcf_ioc_setproperty setprop;
    int prop_fd;
    int ret;

    prop_fd = open("/dev/property", O_RDWR);
    if (prop_fd < 0) {
        perror("Failed to open property device.");
        return prop_fd;
    }

    setprop.property_id = id;
    ret = ioctl(prop_fd, DCF_IOC_GET_PROPERTY, &setprop);
    if (ret)
        perror("Failed to create endpoint.\n");

    if (value)
        *value = setprop.property_value;

    close(prop_fd);

    return ret;
}

