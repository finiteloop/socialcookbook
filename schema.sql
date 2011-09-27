-- Copyright 2011 Bret Taylor
--
-- Licensed under the Apache License, Version 2.0 (the "License"); you may
-- not use this file except in compliance with the License. You may obtain
-- a copy of the License at
--
--     http://www.apache.org/licenses/LICENSE-2.0
--
-- Unless required by applicable law or agreed to in writing, software
-- distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
-- WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
-- License for the specific language governing permissions and limitations
-- under the License.

SET SESSION storage_engine = "InnoDB";
SET SESSION time_zone = "+0:00";
ALTER DATABASE CHARACTER SET "utf8";

DROP TABLE IF EXISTS cookbook_recipes;
CREATE TABLE cookbook_recipes (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    author_id VARCHAR(25) NOT NULL REFERENCES cookbook_users(id),
    slug VARCHAR(100) NOT NULL UNIQUE,
    title VARCHAR(512) NOT NULL,
    category VARCHAR(512) NOT NULL,
    description MEDIUMTEXT NOT NULL,
    ingredients MEDIUMTEXT NOT NULL,
    instructions MEDIUMTEXT NOT NULL,
    created DATETIME NOT NULL,
    updated TIMESTAMP NOT NULL,
    KEY (author_id, created),
    KEY (category)
);

DROP TABLE IF EXISTS cookbook_users;
CREATE TABLE cookbook_users (
    id VARCHAR(25) NOT NULL PRIMARY KEY,
    link VARCHAR(255) NOT NULL,
    name VARCHAR(100) NOT NULL,
    gender VARCHAR(25) NOT NULL,
    access_token VARCHAR(255) NOT NULL,
    created DATETIME NOT NULL,
    updated TIMESTAMP NOT NULL
);

DROP TABLE IF EXISTS cookbook_friends;
CREATE TABLE cookbook_friends (
    user_id VARCHAR(25) NOT NULL,
    friend_id VARCHAR(25) NOT NULL,
    created TIMESTAMP NOT NULL,
    PRIMARY KEY (user_id, friend_id)
);

DROP TABLE IF EXISTS cookbook_clipped;
CREATE TABLE cookbook_clipped (
    user_id VARCHAR(25) NOT NULL REFERENCES cookbook_users(id),
    recipe_id INT NOT NULL REFERENCES cookbook_recipes(id),
    created TIMESTAMP NOT NULL,
    PRIMARY KEY (user_id, recipe_id),
    KEY (user_id, created),
    KEY (recipe_id)
);

DROP TABLE IF EXISTS cookbook_cooked;
CREATE TABLE cookbook_cooked (
    user_id VARCHAR(25) NOT NULL REFERENCES cookbook_users(id),
    recipe_id INT NOT NULL REFERENCES cookbook_recipes(id),
    created TIMESTAMP NOT NULL,
    KEY (user_id, recipe_id),
    KEY (user_id, created),
    KEY (recipe_id)
);

DROP TABLE IF EXISTS cookbook_photos;
CREATE TABLE cookbook_photos (
    recipe_id INT NOT NULL PRIMARY KEY REFERENCES cookbook_recipes(id),
    created TIMESTAMP NOT NULL,
    full_hash VARCHAR(40) NOT NULL,
    full_width INT NOT NULL,
    full_height INT NOT NULL,
    thumb_hash VARCHAR(40) NOT NULL,
    thumb_width INT NOT NULL,
    thumb_height INT NOT NULL
);
