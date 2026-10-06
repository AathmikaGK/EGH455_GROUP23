-- every table has a millisecond ts column, indexed for the history search

CREATE DATABASE IF NOT EXISTS wvs
    DEFAULT CHARACTER SET utf8mb4
    COLLATE utf8mb4_general_ci;

USE wvs;

-- air quality readings from the enviro+ board
CREATE TABLE IF NOT EXISTS readings (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    ts              DATETIME(3) NOT NULL,
    temperature     FLOAT NULL COMMENT 'degrees C',
    pressure        FLOAT NULL COMMENT 'hPa',
    humidity        FLOAT NULL COMMENT 'percent RH',
    light           FLOAT NULL COMMENT 'lux',
    oxidising_ohms  FLOAT NULL COMMENT 'raw resistance, ohms',
    oxidising_ppm   FLOAT NULL COMMENT 'estimated ppm',
    reducing_ohms   FLOAT NULL,
    reducing_ppm    FLOAT NULL,
    ammonia_ohms    FLOAT NULL,
    ammonia_ppm     FLOAT NULL,
    KEY idx_readings_ts (ts)
) ENGINE=InnoDB;

-- one row per target the detection subsystem finds - TAQ
-- the taq sends one list per camera frame, [{"id": 22, "x": .., "y": .., "z": ..}],
-- each marker in the list is a row and they all share the frame's ts.
-- a frame with no markers (None / []) writes no row
CREATE TABLE IF NOT EXISTS detections (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    ts           DATETIME(3) NOT NULL,
    type         ENUM('valve','gauge','aruco') NOT NULL DEFAULT 'aruco',
    valve_state  ENUM('open','closed') NULL,
    gauge_value  FLOAT NULL,
    gauge_units  VARCHAR(16) NULL,
    aruco_id     INT NULL COMMENT 'taq sends this as id',
    x            DOUBLE NULL COMMENT 'metres, camera frame, right',
    y            DOUBLE NULL COMMENT 'metres, camera frame, down',
    z            DOUBLE NULL COMMENT 'metres, camera frame, out of the lens',
    confidence   FLOAT NULL COMMENT '0 to 1',
    frame_path   VARCHAR(255) NULL,
    KEY idx_detections_ts (ts),
    KEY idx_detections_type_ts (type, ts),
    KEY idx_detections_aruco_ts (aruco_id, ts)
) ENGINE=InnoDB;

-- brings a table made from the old schema up to date, safe to run again
ALTER TABLE detections
    MODIFY type ENUM('valve','gauge','aruco') NOT NULL DEFAULT 'aruco',
    MODIFY aruco_id INT NULL COMMENT 'taq sends this as id',
    MODIFY x DOUBLE NULL COMMENT 'metres, camera frame, right',
    MODIFY y DOUBLE NULL COMMENT 'metres, camera frame, down',
    MODIFY z DOUBLE NULL COMMENT 'metres, camera frame, out of the lens',
    ADD KEY IF NOT EXISTS idx_detections_aruco_ts (aruco_id, ts);

-- carries the drill state
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
