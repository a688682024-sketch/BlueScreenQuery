-- =====================================================================
-- 蓝屏代码查询器 2.0 · 内置数据表结构（只读库）
-- ---------------------------------------------------------------------
-- 设计要点
--   1. 内置库随包分发、只读；用户数据（history/favorites/settings）另库。
--   2. meaning / solution 同时保留「原文」与「拆分结果」：
--        meaning_raw  = 原文
--        description  + humor_desc + pro_desc == meaning_raw   （无损）
--        solution_raw = 原文
--        solutions    = 步骤 JSON 数组，"".join(...) == solution_raw（无损）
--      保留原文的目的是可校验、可回溯；拆分结果用于 UI 分区展示。
--   3. 2.0 新增的 aliases / causes / refs 在 v4 数据中并不存在，
--      迁移时一律写入 NULL，UI 显示「暂无信息」，绝不编造（B2=A）。
--   4. 不使用 FTS5：Python 3.8 自带 SQLite 版本较老，缺 trigram 分词器，
--      中文会被 unicode61 近似按整串处理，检索质量反而低于现有子串匹配。
--      2.0 继续沿用 v4 已验证的「内存索引 + 三段式 + LRU」方案。
-- =====================================================================

PRAGMA journal_mode = DELETE;
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- 元数据：数据版本、来源、导入时间、校验和
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- ---------------------------------------------------------------------
-- 停止代码主表
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stop_codes (
    -- 规范化主键：'0X' + 8 位大写十六进制，如 0X0000007B
    stop_code    TEXT PRIMARY KEY,

    -- 展示形式：如 0x0000007B
    display_code TEXT NOT NULL,

    name         TEXT NOT NULL,

    -- JSON 数组字符串；v4 数据无此字段 -> NULL
    aliases      TEXT,

    -- meaning 无损拆分：定义 / 比喻 / 技术
    description  TEXT,
    humor_desc   TEXT,
    pro_desc     TEXT,

    -- meaning 原文，供无损校验与回溯
    meaning_raw  TEXT NOT NULL,

    -- JSON 数组字符串；v4 数据无此字段 -> NULL（显示「暂无信息」）
    causes       TEXT,

    -- 步骤 JSON 数组字符串
    solutions    TEXT,

    -- solution 原文，供无损校验与回溯
    solution_raw TEXT,

    -- 参考信息 JSON 数组字符串；v4 数据无此字段 -> NULL
    refs         TEXT,

    -- 信息 / 警告 / 严重 / 未知
    severity     TEXT NOT NULL DEFAULT '未知',

    category     TEXT,

    source       TEXT,
    data_version TEXT,
    updated_at   TEXT
);

-- 名称检索（大小写不敏感、前缀/包含匹配均可用）
CREATE INDEX IF NOT EXISTS idx_stop_codes_name
    ON stop_codes (name COLLATE NOCASE);

CREATE INDEX IF NOT EXISTS idx_stop_codes_severity
    ON stop_codes (severity);

CREATE INDEX IF NOT EXISTS idx_stop_codes_category
    ON stop_codes (category);
