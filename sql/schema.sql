-- Personal Email Generator — MySQL/MariaDB schema (MVP v2)
-- Import with phpMyAdmin, or run: php bin/setup.php --migrate
--
-- All timestamps are UTC strings. No ENUM (portable, easy to extend).

CREATE TABLE IF NOT EXISTS `admin` (
    `id`             INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `username`       VARCHAR(64)  NOT NULL,
    `password_hash`  VARCHAR(255) NOT NULL,
    `session_epoch`  INT UNSIGNED NOT NULL DEFAULT 1,
    `failed_count`   INT UNSIGNED NOT NULL DEFAULT 0,
    `locked_until`   DATETIME     NULL,
    `last_login_at`  DATETIME     NULL,
    `last_login_ip`  VARCHAR(45)  NULL,
    `created_at`     DATETIME     NOT NULL,
    `updated_at`     DATETIME     NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_admin_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `settings` (
    `k`          VARCHAR(64) NOT NULL,
    `v`          TEXT        NULL,
    `updated_at` DATETIME    NOT NULL,
    PRIMARY KEY (`k`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `addresses` (
    `id`                     INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `address`                VARCHAR(254) NOT NULL,
    `local_part`             VARCHAR(64)  NOT NULL,
    `domain`                 VARCHAR(190) NOT NULL,
    `label`                  VARCHAR(64)  NULL,
    `status`                 VARCHAR(20)  NOT NULL DEFAULT 'pending',
    `password_enc`           VARBINARY(512) NULL,
    `quota_mb`               INT UNSIGNED NOT NULL DEFAULT 100,
    `forward_to`             VARCHAR(254) NULL,
    `server_verified_at`     DATETIME     NULL,
    `forwarder_verified_at`  DATETIME     NULL,
    `imap_verified_at`       DATETIME     NULL,
    `first_external_mail_at` DATETIME     NULL,
    `forward_confirmed_at`   DATETIME     NULL,
    `imap_uidvalidity`       BIGINT UNSIGNED NULL,
    `imap_last_uid`          BIGINT UNSIGNED NOT NULL DEFAULT 0,
    `last_synced_at`         DATETIME     NULL,
    `last_error`             VARCHAR(500) NULL,
    `created_at`             DATETIME     NOT NULL,
    `updated_at`             DATETIME     NOT NULL,
    `deleted_at`             DATETIME     NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_address` (`address`),
    KEY `idx_status` (`status`),
    KEY `idx_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `messages` (
    `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `address_id`  INT UNSIGNED NOT NULL,
    `uidvalidity` BIGINT UNSIGNED NOT NULL,
    `uid`         BIGINT UNSIGNED NOT NULL,
    `message_id`  VARCHAR(255) NULL,
    `from_addr`   VARCHAR(254) NULL,
    `from_name`   VARCHAR(190) NULL,
    `subject`     VARCHAR(500) NULL,
    `sent_at`     DATETIME     NULL,
    `is_read`     TINYINT(1)   NOT NULL DEFAULT 0,
    `created_at`  DATETIME     NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_message` (`address_id`, `uidvalidity`, `uid`),
    KEY `idx_addr_sent` (`address_id`, `sent_at`),
    CONSTRAINT `fk_messages_address` FOREIGN KEY (`address_id`)
        REFERENCES `addresses` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `login_attempts` (
    `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `ip`         VARCHAR(45) NOT NULL,
    `username`   VARCHAR(64) NOT NULL,
    `ok`         TINYINT(1)  NOT NULL DEFAULT 0,
    `created_at` DATETIME    NOT NULL,
    PRIMARY KEY (`id`),
    KEY `idx_ip_time` (`ip`, `created_at`),
    KEY `idx_user_time` (`username`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `throttle` (
    `bucket`       VARCHAR(32)  NOT NULL,
    `key_hash`     CHAR(64)     NOT NULL,
    `window_start` INT UNSIGNED NOT NULL,
    `counter`      INT UNSIGNED NOT NULL DEFAULT 0,
    PRIMARY KEY (`bucket`, `key_hash`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
