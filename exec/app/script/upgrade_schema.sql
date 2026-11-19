-- 本机升级包记录，仅创建一张表。
CREATE TABLE IF NOT EXISTS upgrade_packages (
	sha256 VARCHAR(64) NOT NULL, 
	firmware VARCHAR(32) NOT NULL, 
	version VARCHAR(255) NOT NULL, 
	path TEXT NOT NULL, 
	record LONGTEXT NOT NULL, 
	uploaded_at DATETIME NOT NULL,
	is_current BOOL NOT NULL DEFAULT 0, 
	PRIMARY KEY (sha256),
	KEY ix_upgrade_packages_firmware (firmware)
)CHARSET=utf8mb4 ENGINE=InnoDB;
