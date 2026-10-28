<?php

/**
 * Example configuration.
 *
 * Copy to config/config.php (same directory) and fill in the values.
 * On cPanel the whole `config/` directory lives OUTSIDE the subdomain document
 * root, so this file is never reachable over HTTP. Keep permissions at 0600.
 *
 * Generate the app key with:  php bin/setup.php --print-key
 */

return [
    'app' => [
        'name' => 'Personal Email Generator',
        // Public base URL of the dashboard (no trailing slash).
        'base_url' => 'https://app.example.com',
        // 'production' or 'local'. 'local' enables verbose errors — never on a live host.
        'env' => 'production',
        'timezone' => 'UTC',
        'debug' => false,
    ],

    'db' => [
        // MySQL/MariaDB. Create the database and a dedicated user in cPanel first.
        'dsn' => 'mysql:host=localhost;dbname=cpuser_mailapp;charset=utf8mb4',
        'user' => 'cpuser_mailapp',
        'pass' => 'CHANGE_ME',
    ],

    'session' => [
        'name' => 'mailgen_session',
        'idle_seconds' => 1800,      // 30 minutes
        'absolute_seconds' => 43200, // 12 hours
    ],

    'security' => [
        // 32 random bytes, base64 encoded. Generate with bin/setup.php --print-key.
        'app_key' => 'CHANGE_ME_BASE64_32_BYTES',
        // Maximum failed logins before the account/IP is temporarily locked.
        'login_max_attempts' => 5,
        'login_window_seconds' => 900,
    ],

    'cpanel' => [
        // cPanel API endpoint. Port 2083 is the standard HTTPS API port.
        'base_url' => 'https://server.example.com:2083',
        'user' => 'cpuser',
        // Create under cPanel > Security > Manage API Tokens. Full-account power: 0600 file only.
        'token' => 'CHANGE_ME',
        'timeout_seconds' => 25,
        // Keep TLS verification on. Only disable for a local mock server in tests.
        'verify_tls' => true,
        'ca_bundle' => null,
    ],

    'mail' => [
        // Domain that generated addresses belong to. It must be a mail domain on this account.
        'address_domain' => 'example.com',
        'address_prefix' => 'otp-',
        'address_length' => 10,
        // Where every generated address is forwarded. Must be a real mailbox you can read.
        'forward_to' => 'primary@example.com',
        'max_addresses' => 10,
        'quota_mb' => 100,

        'imap' => [
            'host' => 'example.com',     // usually mail.<domain> or the server hostname
            'port' => 993,
            'encryption' => 'ssl',       // 'ssl' (993) or 'tls' (143)
            'validate_cert' => true,
            'timeout' => 20,
            // 'webklex' (production) or 'fake' (tests only; refused when env=production)
            'driver' => 'webklex',
            'sync_batch' => 5,           // addresses per sync request
            'sync_max_messages' => 100,  // messages imported per address per run
        ],
    ],

    'cron' => [
        // Shared secret for bin/cron.php when invoked over HTTP (optional).
        'key' => 'CHANGE_ME_RANDOM',
    ],
];
