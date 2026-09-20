# #添加本地文件
# SUBDIRS := ./lc_data

# #添加lib目录中的库文件
# LIB_SRC=$(wildcard ./lib/*.c)
# LIB_OBJ=$(patsubst ./lib/%.c, ../lib/%.o, $(LIB_SRC))

# #配置
# MAKE = make

# #执行内容
# all: $(SUBDIRS)

# $(SUBDIRS): ECHO
# 	$(MAKE) -C $@

# ECHO:
# 	@echo $(SUBDIRS)

# #命令
# .PHONY: clean
# clean:
# 	rm $(LIB_OBJ)


# ======================
# 目录配置
# ======================

# 子项目目录（根据实际项目名称修改）
SUBDIRS := ./lc_data

# 库文件配置（注意路径一致性）
LIB_SRC  = $(wildcard ./lib/*.c)
LIB_OBJ  = $(patsubst ./lib/%.c, ./lib/%.o, $(LIB_SRC))  # 修正为同级lib目录

# ======================
# 构建配置
# ======================

# 工具链配置
MAKE     = make
RM      := rm -f

# ======================
# 构建规则
# ======================

# 默认构建目标
all: verify_dirs $(SUBDIRS)

# 递归构建子目录
$(SUBDIRS): ECHO
	@$(MAKE) -C $@

# 路径验证（可选）
.PHONY: verify_dirs
verify_dirs:
	@test -d ./lib || (echo "Error: lib directory missing!"; exit 1)

# 构建信息输出
ECHO:
	@echo "Building subsystems: $(SUBDIRS)"

# ======================
# 清理规则
# ======================

.PHONY: clean
clean:
	@$(RM) $(LIB_OBJ)
	@for dir in $(SUBDIRS); do \
		$(MAKE) -C $$dir clean; \
	done
	@echo "Clean completed"

# ======================
# 伪目标声明
# ======================
.PHONY: all ECHO
