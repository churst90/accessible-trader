-- Database: user_configs_db (Create this database separately if it doesn't exist)
-- MariaDB / MySQL Schema for User Configurations

CREATE DATABASE IF NOT EXISTS user_configs_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0; -- Disable for setup, enable at the end
SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO"; -- Or your preferred SQL mode
SET time_zone = "+00:00";

-- --------------------------------------------------------
-- Table structure for table `user_api_credentials`
-- Stores API keys for external services/plugins, linked to a user.
-- --------------------------------------------------------
DROP TABLE IF EXISTS `user_api_credentials`;
CREATE TABLE `user_api_credentials` (
  `credential_id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Primary key for the credential',
  `user_id` INT UNSIGNED NOT NULL COMMENT 'Foreign key referencing the main users table ID',
  `service_name` VARCHAR(100) NOT NULL COMMENT 'Identifier for the service/plugin (e.g., alpaca, oanda, fmp)',
  `credential_name` VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'User-defined alias/name for this API key set',
  `encrypted_api_key` TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL COMMENT 'Encrypted API key (application-level encryption)',
  `encrypted_api_secret` TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL DEFAULT NULL COMMENT 'Encrypted API secret (application-level encryption)',
  `encrypted_aux_data` TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL DEFAULT NULL COMMENT 'Encrypted auxiliary data like OANDA Account ID or passphrases (application-level encryption)',
  `is_testnet` BOOLEAN NOT NULL DEFAULT FALSE COMMENT '0 for live environment, 1 for sandbox/testnet',
  `notes` TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT 'User-supplied notes about this credential',
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`credential_id`),
  INDEX `idx_user_id_service_name` (`user_id`, `service_name`),
  UNIQUE KEY `uk_user_service_credential_name` (`user_id`, `service_name`, `credential_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Stores user-provided API credentials for various services.';

-- --------------------------------------------------------
-- Table structure for table `user_chart_layouts`
-- Stores user-saved chart configurations (layouts, indicators, drawings).
-- --------------------------------------------------------
DROP TABLE IF EXISTS `user_chart_layouts`;
CREATE TABLE `user_chart_layouts` (
  `layout_id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Primary key for the saved chart layout',
  `user_id` INT UNSIGNED NOT NULL COMMENT 'Foreign key referencing the main users table ID',
  `layout_name` VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'User-defined name for this chart layout',
  `market` VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Market context (e.g., crypto, us_equity)',
  `provider` VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Provider context (e.g., binance, alpaca)',
  `symbol` VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Instrument symbol (e.g., BTC/USD, AAPL)',
  `timeframe` VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Chart timeframe (e.g., 1m, 1h, 1d)',
  `layout_config_json` JSON NOT NULL COMMENT 'JSON object storing all chart settings: indicators, drawings, scale, zoom, etc.',
  `is_default_for_instrument` BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'Is this the default layout when this instrument is opened?',
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`layout_id`),
  INDEX `idx_user_id` (`user_id`),
  UNIQUE KEY `uk_user_layout_name` (`user_id`, `layout_name`),
  INDEX `idx_user_instrument_lookup` (`user_id`, `market`, `provider`, `symbol`, `timeframe`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Stores user-saved chart layouts and configurations.';

-- --------------------------------------------------------
-- Table structure for table `user_general_preferences`
-- Stores general UI and application preferences for a user.
-- --------------------------------------------------------
DROP TABLE IF EXISTS `user_general_preferences`;
CREATE TABLE `user_general_preferences` (
  `user_id` INT UNSIGNED NOT NULL COMMENT 'Primary key, also Foreign key referencing the main users table ID',
  `ui_theme` VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'light' COMMENT 'User interface theme (e.g., light, dark)',
  `default_chart_market` VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT 'User''s preferred default market for new charts',
  `default_chart_provider` VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT 'User''s preferred default provider',
  `default_chart_timeframe` VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT 'User''s preferred default timeframe',
  `other_settings_json` JSON NULL DEFAULT NULL COMMENT 'JSON object for miscellaneous future settings',
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Stores general user interface and application preferences.';

-- --------------------------------------------------------
-- Table structure for table `user_indicator_presets`
-- Stores user-defined presets for indicator configurations for quick reuse.
-- --------------------------------------------------------
DROP TABLE IF EXISTS `user_indicator_presets`;
CREATE TABLE `user_indicator_presets` (
  `preset_id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Primary key for the indicator preset',
  `user_id` INT UNSIGNED NOT NULL COMMENT 'Foreign key referencing the main users table ID',
  `indicator_type` VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Type of indicator (e.g., SMA, RSI, MACD)',
  `preset_name` VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'User-defined name for this preset',
  `params_json` JSON NOT NULL COMMENT 'JSON object storing the parameters for this indicator preset (e.g., {"period": 14})',
  `visual_config_json` JSON NULL DEFAULT NULL COMMENT 'JSON object for visual settings (color, line width etc.)',
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`preset_id`),
  INDEX `idx_user_id_indicator_type` (`user_id`, `indicator_type`),
  UNIQUE KEY `uk_user_indicator_preset_name` (`user_id`, `indicator_type`, `preset_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Stores user-saved presets for indicator configurations.';

SET FOREIGN_KEY_CHECKS = 1; -- Re-enable foreign key checks