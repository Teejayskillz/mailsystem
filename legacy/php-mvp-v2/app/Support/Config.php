<?php

declare(strict_types=1);

namespace App\Support;

/**
 * Immutable configuration wrapper with dot-notation access.
 */
final class Config
{
    /** @param array<string, mixed> $data */
    private function __construct(
        private readonly array $data,
        private readonly string $path,
    ) {
    }

    public static function load(string $path): self
    {
        if (!is_file($path)) {
            throw new ConfigException('Configuration file not found: ' . $path);
        }

        $data = require $path;

        if (!is_array($data)) {
            throw new ConfigException('Configuration file must return an array: ' . $path);
        }

        return new self($data, $path);
    }

    /** @param array<string, mixed> $data */
    public static function fromArray(array $data, string $path = '<array>'): self
    {
        return new self($data, $path);
    }

    public function path(): string
    {
        return $this->path;
    }

    public function get(string $key, mixed $default = null): mixed
    {
        $cursor = $this->data;

        foreach (explode('.', $key) as $segment) {
            if (!is_array($cursor) || !array_key_exists($segment, $cursor)) {
                return $default;
            }
            $cursor = $cursor[$segment];
        }

        return $cursor;
    }

    public function has(string $key): bool
    {
        return $this->get($key, self::class) !== self::class;
    }

    public function string(string $key, ?string $default = null): string
    {
        $value = $this->get($key, $default);

        if (!is_string($value) || $value === '') {
            throw new ConfigException('Missing or empty configuration value: ' . $key);
        }

        return $value;
    }

    public function int(string $key, int $default = 0): int
    {
        $value = $this->get($key, $default);

        return is_numeric($value) ? (int) $value : $default;
    }

    public function bool(string $key, bool $default = false): bool
    {
        $value = $this->get($key, $default);

        return is_bool($value) ? $value : (bool) $value;
    }

    /**
     * Fail fast on obviously unconfigured values (still present as CHANGE_ME placeholders).
     */
    public function assertConfigured(): void
    {
        $required = [
            'db.dsn',
            'db.user',
            'security.app_key',
            'cpanel.base_url',
            'cpanel.user',
            'cpanel.token',
            'mail.address_domain',
            'mail.forward_to',
            'mail.imap.host',
        ];

        $missing = [];
        foreach ($required as $key) {
            $value = $this->get($key);
            if (!is_string($value) || $value === '' || str_contains($value, 'CHANGE_ME')) {
                $missing[] = $key;
            }
        }

        if ($missing !== []) {
            throw new ConfigException(
                'Configuration incomplete. Set these values in ' . $this->path . ': ' . implode(', ', $missing)
            );
        }
    }

    /** @return array<string, mixed> */
    public function all(): array
    {
        return $this->data;
    }
}
