-- =====================================================================
-- 蓝屏代码查询器 2.0 · 用户数据库结构（可写库）
-- ---------------------------------------------------------------------
-- 与内置库（data/schema.sql）完全分离：
--   内置库 = 只读语料，随包分发
--   用户库 = 本文件，可删可重建，绝不触碰语料
-- 所有写入均由 UserRepository 包裹在单事务内完成。
-- =====================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- 搜索历史：去重靠 normalized_query，只保留最近 N 条（默认 50）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS history (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_query        TEXT NOT NULL,
    normalized_query TEXT NOT NULL,
    stop_code        TEXT,
    created_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_history_normalized
    ON history (normalized_query);

CREATE INDEX IF NOT EXISTS idx_history_recency
    ON history (id DESC);

-- ---------------------------------------------------------------------
-- 收藏：stop_code 作主键，天然幂等，重复收藏不会产生第二行
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS favorites (
    stop_code  TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);

-- ---------------------------------------------------------------------
-- 设置：值为 JSON 文本，可存字符串/数字/布尔/列表/对象
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT
);

-- ---------------------------------------------------------------------
-- 数据元信息：内置数据版本、来源、导入时间、校验和
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS data_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- ---------------------------------------------------------------------
-- 用户库自身的 schema 版本，供将来迁移
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_info (
    version TEXT PRIMARY KEY
);
