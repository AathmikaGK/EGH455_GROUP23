-- every table has a millisecond ts column, indexed for the history search

CREATE DATABASE IF NOT EXISTS wvs
    DEFAULT CHARACTER SET utf8mb4
    COLLATE utf8mb4_general_ci;

USE wvs;

-- AQ readings retain the field names and values emitted by SensorController.
CREATE TABLE IF NOT EXISTS readings (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    ts              DATETIME(3) NOT NULL COMMENT 'webviz arrival time',
    `timestamp`     DATETIME(6) NOT NULL COMMENT 'AQ source timestamp',
    temperature     FLOAT NULL COMMENT 'degrees C',
    pressure        FLOAT NULL COMMENT 'hPa',
    humidity        FLOAT NULL COMMENT 'percent RH',
    light           FLOAT NULL COMMENT 'lux',
    proximity       INT NULL,
    oxidising       FLOAT NULL,
    reducing        FLOAT NULL,
    nh3             FLOAT NULL,
    KEY idx_readings_ts (ts),
    KEY idx_readings_source_timestamp (`timestamp`)
) ENGINE=InnoDB;

-- one row per target the detection subsystem finds
CREATE TABLE IF NOT EXISTS detections (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    ts           DATETIME(3) NOT NULL,
    type         ENUM('valve','gauge','aruco') NOT NULL,
    valve_state  ENUM('open','closed') NULL,
    gauge_value  FLOAT NULL,
    gauge_units  VARCHAR(16) NULL,
    aruco_id     INT NULL,
    x            FLOAT NULL COMMENT 'metres',
    y            FLOAT NULL COMMENT 'metres',
    z            FLOAT NULL COMMENT 'metres',
    confidence   FLOAT NULL COMMENT '0 to 1',
    frame_path   VARCHAR(255) NULL,
    KEY idx_detections_ts (ts),
    KEY idx_detections_type_ts (type, ts)
) ENGINE=InnoDB;

-- general messages from any subsystem, also carries the drill state
CREATE TABLE IF NOT EXISTS system_log (
    id               BIGINT AUTO_INCREMENT PRIMARY KEY,
    ts               DATETIME(3) NOT NULL,
    level            ENUM('info','warning','error') NOT NULL DEFAULT 'info',
    component        VARCHAR(64) NOT NULL,
    message          VARCHAR(255) NOT NULL,
    drill_state      ENUM('idle','drilling','done') NULL,
    hole_depth       FLOAT NULL COMMENT 'metres',
    trigger_pressure FLOAT NULL COMMENT 'bar',
    KEY idx_system_log_ts (ts),
    KEY idx_system_log_level_ts (level, ts)
) ENGINE=InnoDB;

-- the web app logs in as this user, it never needs to change the schema
CREATE USER IF NOT EXISTS 'webviz'@'localhost' IDENTIFIED BY 'webviz';
GRANT SELECT, INSERT, UPDATE, DELETE ON wvs.* TO 'webviz'@'localhost';
FLUSH PRIVILEGES;
