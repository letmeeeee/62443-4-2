# 目录配置
BUILD_DIR = ../build
OBJ_DIR = $(BUILD_DIR)/obj
LIB_OBJ_DIR = $(BUILD_DIR)/lib

# 源文件配置
LOCAL_SRC = $(wildcard ./*.c)
LOCAL_OBJ = $(patsubst ./%.c, $(OBJ_DIR)/%.o, $(LOCAL_SRC))
LIB_SRC = $(wildcard ../lib/*.c)
LIB_OBJ = $(patsubst ../lib/%.c, $(LIB_OBJ_DIR)/%.o, $(LIB_SRC))

# 工具链配置
CC = aarch64-linux-gnu-gcc

# 编译选项
CFLAGS = -I../include -I../include/lib -g -Wall -std=gnu99 -pthread
LDFLAGS = -L../lib -pthread -lzlog -lm -lmysqlclient -lssl -lcrypto -lrt

# 确保链接顺序正确（需要依赖关系的库放在后面）
LIBS = -lstdc++

# 默认目标
all: lc_data

# 主构建规则
lc_data: $(LOCAL_OBJ) $(LIB_OBJ)
	@mkdir -p $(@D)
	$(CC) $^ $(LDFLAGS) $(LIBS) -o $@

# 本地对象构建规则
$(OBJ_DIR)/%.o: ./%.c
	@mkdir -p $(@D)
	$(CC) $(CFLAGS) -c $< -o $@

# 库对象构建规则
$(LIB_OBJ_DIR)/%.o: ../lib/%.c
	@mkdir -p $(@D)
	$(CC) $(CFLAGS) -c $< -o $@

# 清理规则
.PHONY: clean
clean:
	rm -rf $(BUILD_DIR) lc_data

# 伪目标声明
.PHONY: all



# #添加本地文件
# LOCAL_SRC=$(wildcard ./*.c)
# LOCAL_OBJ=$(patsubst ./%.c, ./%.o, $(LOCAL_SRC))

# #添加lib目录中的库文件
# LIB_SRC=$(wildcard ../lib/*.c)
# LIB_OBJ=$(patsubst ../lib/%.c, ../lib/%.o, $(LIB_SRC))

# #配置
# CC=aarch64-linux-gnu-gcc
# INCLUDES = -I../include -I../include/lib
# LIBS += -L../lib -lpthread -lzlog -std=gnu99 -lm -lmysqlclient -lssl -lcrypto -lrt -lstdc++
# #LIBS += -L../lib -lpthread -lzlog -std=gnu99 -lm
# #编译过程
# lc_data:$(LOCAL_OBJ) $(LIB_OBJ)
# 	rm -rf lc_data
# 	$(CC)  $^ $(LIBS) $(INCLUDES) $(MACRO) -g -o $@
# 	@rm $(LOCAL_OBJ) $(LIB_OBJ)

# %.o: %.c
# 	$(CC) $(LIBS) $(INCLUDES) $(MACRO) -g -c $^ -o $@

# #命令
# .PHONY: clean

# clean:
# 	rm -f *.o ../lib/*.o


# # 目录配置
# BUILD_DIR = ../build
# LIB_DIR = $(BUILD_DIR)/lib

# # 源文件配置
# LOCAL_SRC = $(wildcard ./*.c)
# LOCAL_OBJ = $(patsubst ./%.c, $(BUILD_DIR)/%.o, $(LOCAL_SRC))
# LIB_SRC = $(wildcard ../lib/*.c)
# LIB_OBJ = $(patsubst ../lib/%.c, $(LIB_DIR)/%.o, $(LIB_SRC))

# # 工具链与编译选项
# CC = aarch64-linux-gnu-gcc
# INCLUDES = -I../include -I../include/lib
# CFLAGS = $(INCLUDES) -g -Wall -pthread
# LDFLAGS = -L../lib -g -pthread -lzlog -lm  # 确保 -pthread 在依赖库前

# # 编译规则
# $(BUILD_DIR)/%.o: ./%.c
	
# 	mkdir -p $(@D)
# 	$(CC) $(CFLAGS) -c $< -o $@

# $(LIB_DIR)/%.o: ../lib/%.c
# 	mkdir -p $(@D)
# 	$(CC) $(CFLAGS) -c $< -o $@

# # 链接规则
# tems: $(LOCAL_OBJ) $(LIB_OBJ)
# 	$(CC) $^ $(LDFLAGS) -o $@

# # 清理
# .PHONY: clean
# clean:
# 	rm -rf $(BUILD_DIR) tems
