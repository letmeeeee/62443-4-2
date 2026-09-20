#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <termios.h>
#include <errno.h>
#include <string.h>

#define EXPORT_PATH "/sys/class/gpio/export\0"            // GPIO设备导出设备
#define OUT         "out\0"
#define IN          "in\0"
#define HIGH_LEVEL  "1\0"
#define LOW_LEVEL   "0\0"

int	get_di_state(int port, int *state)
{
	const static char DEV_GPIO[18][4] = 
	{"291\0","287\0","288\0","289\0","285\0","286\0","298\0","297\0","380\0","381\0",
	"382\0","383\0","384\0","385\0","386\0","387\0","388\0","389\0"};
	// 输入输出电平值设备
	const static char DEV_PATH[18][30] = 
	{"/sys/class/gpio/gpio291/value\0",
	"/sys/class/gpio/gpio287/value\0",
	"/sys/class/gpio/gpio288/value\0",
	"/sys/class/gpio/gpio289/value\0",
	"/sys/class/gpio/gpio285/value\0",
	"/sys/class/gpio/gpio286/value\0",
	"/sys/class/gpio/gpio298/value\0",
	"/sys/class/gpio/gpio297/value\0",
	"/sys/class/gpio/gpio380/value\0",
	"/sys/class/gpio/gpio381/value\0",
	"/sys/class/gpio/gpio382/value\0",
	"/sys/class/gpio/gpio383/value\0",
	"/sys/class/gpio/gpio384/value\0",
	"/sys/class/gpio/gpio385/value\0",
	"/sys/class/gpio/gpio386/value\0",
	"/sys/class/gpio/gpio387/value\0",
	"/sys/class/gpio/gpio388/value\0",
	"/sys/class/gpio/gpio389/value\0"
	};
	// GPIO输入输出控制设备
	const static char DIRECT_PATH[18][34] = 
	{"/sys/class/gpio/gpio291/direction\0",
	"/sys/class/gpio/gpio287/direction\0",
	"/sys/class/gpio/gpio288/direction\0",
	"/sys/class/gpio/gpio289/direction\0",
	"/sys/class/gpio/gpio285/direction\0",
	"/sys/class/gpio/gpio286/direction\0",
	"/sys/class/gpio/gpio298/direction\0",
	"/sys/class/gpio/gpio297/direction\0",
	"/sys/class/gpio/gpio380/direction\0",
	"/sys/class/gpio/gpio381/direction\0",
	"/sys/class/gpio/gpio382/direction\0",
	"/sys/class/gpio/gpio383/direction\0",
	"/sys/class/gpio/gpio384/direction\0",
	"/sys/class/gpio/gpio385/direction\0",
	"/sys/class/gpio/gpio386/direction\0",
	"/sys/class/gpio/gpio387/direction\0",
	"/sys/class/gpio/gpio388/direction\0",
	"/sys/class/gpio/gpio389/direction\0"
	};
    static int fd_dev[18], fd_dir[18], ret[18];
    static int fd_export[18] = {-2,-2,-2,-2,-2, -2,-2,-2,-2,-2, 2,-2,-2,-2,-2, 2,-2,-2};
    char buf[10], direction[4];
    if(fd_export[port]< 0)
    {
        fd_export[port] = open(EXPORT_PATH, O_WRONLY);            // 打开GPIO设备导出设备
        if(fd_export[port] < 0) {
            printf("open export err:%d\n",fd_export[port]);
            return -1;
        }
        write(fd_export[port], DEV_GPIO[port], strlen(DEV_GPIO[port]));
    }
    
    fd_dev[port]  = open(DEV_PATH[port], O_RDWR);                    // 打开输入输出电平值设备
    if(fd_dev[port]  < 0) {
        close(fd_export[port]);
        fd_export[port] = -3;
        printf("open gpio err:%s\n",DEV_PATH[port]);
        return -1;
    }
    fd_dir[port]  = open(DIRECT_PATH[port], O_RDWR);                 // 打开GPIO输入输出控制设备
    if(fd_dir[port]  < 0) {
        close(fd_dev[port]);
        close(fd_export[port]);
        fd_export[port] = -3;
		printf("open direction err:%s\n",DIRECT_PATH[port]);
        return -1;
    }
    ret[port]  = read(fd_dir[port], direction, sizeof(direction));   // 读取输入输出方向
    if(ret[port]  < 0) {
        printf("read direction err:%d\n",ret[port]);
        close(fd_export[port]);
        fd_export[port] = -3;
        close(fd_dir[port]);
        close(fd_dev[port]);
        return -1;
    }
    printf("default direction :%s\n", direction );
    if(strncmp(direction, IN,strlen(IN)) != 0)
    {
        printf("Set direction IN\n");
        strcpy(buf, IN);
        ret[port] = write(fd_dir[port] , buf, strlen(IN));
        if(ret < 0) {
            printf("write direction err:%d\n",ret[port]);
            close(fd_export[port] );
            fd_export[port] = -3;
            close(fd_dir[port] );
            close(fd_dev[port] );
            return -1;
        }
        ret[port] = read(fd_dir[port], direction, sizeof(direction));
        if(ret[port] < 0) {
            printf("read direction err:%d\n",ret[port]);
            close(fd_export[port]);
            fd_export[port] = -3;
            close(fd_dir[port]);
            close(fd_dev[port]);
            return -1;
        }
    }
    ret[port] = read(fd_dev[port], buf, sizeof(buf));               // 读取GPIO1_0输入电平值
    if(ret[port] < 0) {
        printf("read gpio err:%d\n",ret[port]);
        close(fd_export[port]);
        fd_export[port] = -3;
        close(fd_dir[port]);
        close(fd_dev[port]);
        return -1;
    }
    printf("current direction:%sinput level:%s\n", direction, buf);
	if(strncmp(buf, LOW_LEVEL,strlen(LOW_LEVEL)) == 0)
	{
		(*state) = 0;
	}
	else if(strncmp(buf, HIGH_LEVEL,strlen(HIGH_LEVEL)) == 0)
	{
		(*state) = 1;
	}
	else
	{
		(*state) = -1;
	}
    close(fd_dir[port]);
    close(fd_dev[port]);
    return 0;
}


int	set_do_state(int port, int state)
{
	const static char DEV_GPIO[8][4] = 
	{"390\0","391\0","392\0","393\0","394\0","395\0","396\0","398\0"};
	// 输入输出电平值设备
	const static char DEV_PATH[8][30] = 
	{"/sys/class/gpio/gpio390/value\0",
	"/sys/class/gpio/gpio391/value\0",
	"/sys/class/gpio/gpio392/value\0",
	"/sys/class/gpio/gpio393/value\0",
	"/sys/class/gpio/gpio394/value\0",
	"/sys/class/gpio/gpio395/value\0",
	"/sys/class/gpio/gpio396/value\0",
	"/sys/class/gpio/gpio398/value\0"
	};
	// GPIO输入输出控制设备
	const static char DIRECT_PATH[8][34] = 
	{"/sys/class/gpio/gpio390/direction\0",
	"/sys/class/gpio/gpio391/direction\0",
	"/sys/class/gpio/gpio392/direction\0",
	"/sys/class/gpio/gpio393/direction\0",
	"/sys/class/gpio/gpio394/direction\0",
	"/sys/class/gpio/gpio395/direction\0",
	"/sys/class/gpio/gpio396/direction\0",
	"/sys/class/gpio/gpio398/direction\0"
	};
    static int fd_dev[8], fd_dir[8], ret[8];
    static int fd_export[8] = {-2,-2,-2,-2,-2, -2,-2,-2};
    char buf[10], direction[4];

    if(fd_export[port]< 0)
    {
        fd_export[port] = open(EXPORT_PATH, O_WRONLY);            // 打开GPIO设备导出设备
        if(fd_export[port] < 0) {
            printf("open export err:%d\n",fd_export[port]);
            return -1;
        }
        write(fd_export[port], DEV_GPIO[port], strlen(DEV_GPIO[port]));
    }
    fd_dev[port]  = open(DEV_PATH[port], O_RDWR);                    // 打开输入输出电平值设备
    if(fd_dev[port]  < 0) {
        close(fd_export[port]);
        fd_export[port] = -3;
        printf("open gpio err:%s\n",DEV_PATH[port]);
        return -1;
    }
    fd_dir[port]  = open(DIRECT_PATH[port], O_RDWR);                 // 打开GPIO输入输出控制设备
    if(fd_dir[port]  < 0) {
        close(fd_export[port]);
        fd_export[port] = -3;
        close(fd_dev[port]);
        printf("open direction err:%s\n",DIRECT_PATH[port]);
        return -1;
    }
    ret[port]  = read(fd_dir[port], direction, sizeof(direction));   // 读取输入输出方向
    if(ret[port]  < 0) {
        printf("read direction err:%d\n",ret[port]);
        close(fd_export[port]);
        fd_export[port] = -3;
        close(fd_dir[port]);
        close(fd_dev[port]);
        return -1;
    }
    printf("default direction :%s\n", direction);
    if(strncmp(direction, OUT,strlen(OUT)) != 0)
    {
        printf("Set direction OUT\n");
        strcpy(buf, OUT);
        ret[port] = write(fd_dir[port] , buf, strlen(OUT));
        if(ret[port] < 0) {
            printf("write direction err:%d\n",ret[port]);
            close(fd_export[port] );
            fd_export[port] = -3;
            close(fd_dir[port] );
            close(fd_dev[port] );
            return -1;
        }
        ret[port] = read(fd_dir[port], direction, sizeof(direction));
        if(ret[port] < 0) {
            printf("read direction err:%d\n",ret[port]);
            close(fd_export[port]);
            fd_export[port] = -3;
            close(fd_dir[port]);
            close(fd_dev[port]);
            return -1;
        }
    }
	if(state==0)
	{
		ret[port] = write(fd_dev[port] , LOW_LEVEL, strlen(LOW_LEVEL));
	}
	else
	{
		ret[port] = write(fd_dev[port] , HIGH_LEVEL, strlen(HIGH_LEVEL));
	}
	printf("gpio:%s,current direction:%s,output level:%d\n",DEV_GPIO[port],direction, state);
    if(ret[port] < 0) {
        printf("write level err:%d\n",ret[port]);
        close(fd_export[port] );
        fd_export[port] = -3;
        close(fd_dir[port] );
        close(fd_dev[port] );
        return -1;
    }
    close(fd_dir[port]);
    close(fd_dev[port]);
    return 0;
}