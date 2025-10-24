# Podman Setup for GuideAI Telemetry Pipeline

> **Recommended for:** Users seeking a lightweight Docker Desktop alternative
> **Podman Version:** 4.0+ required
> **Compatibility:** Full Docker Compose compatibility via podman-compose

## Why Podman?
- ✅ **Lighter weight** - No daemon process, smaller memory footprint
- ✅ **Rootless by default** - Better security
- ✅ **Docker compatible** - Drop-in replacement for most docker commands
- ✅ **Open source** - Apache 2.0 license
- ✅ **Native macOS support** - Via podman machine

## Installation (macOS)

### Option 1: Homebrew (Recommended)
```bash
# Install Podman
brew install podman

# Install podman-compose
brew install podman-compose

# Verify installation
podman --version
podman-compose --version
```

### Option 2: Podman Desktop (GUI)
```bash
# Install Podman Desktop (includes GUI and CLI)
brew install --cask podman-desktop
```

## Initial Setup

### 1. Create Podman Machine
```bash
# Initialize Podman VM (similar to Docker Desktop VM)
podman machine init --cpus 4 --memory 4096 --disk-size 50

# Start the machine
podman machine start

# Verify status
podman machine list
podman info
```

### 2. Configure Podman for GuideAI
```bash
# Set alias for Docker commands (optional)
alias docker=podman
alias docker-compose=podman-compose

# Add to ~/.zshrc for persistence
echo "alias docker=podman" >> ~/.zshrc
echo "alias docker-compose=podman-compose" >> ~/.zshrc
```

## Running Telemetry Pipeline with Podman

### Start Infrastructure
```bash
# Navigate to project root
cd /Users/nick/guideai

# Start services with podman-compose
podman-compose -f docker-compose.telemetry.yml up -d

# Verify services
podman ps
```

### Alternative: Use Podman Directly
```bash
# Podman natively supports Docker Compose files
podman play kube --start docker-compose.telemetry.yml

# Or use podman-compose (more compatible)
podman-compose -f docker-compose.telemetry.yml up -d
```

### Stop Services
```bash
podman-compose -f docker-compose.telemetry.yml down

# Or stop all containers
podman stop --all
```

## Validation with Podman

```bash
# Run validation script (auto-detects Podman)
./scripts/validate_telemetry_pipeline.sh

# Check containers
podman ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# View logs
podman logs guideai-kafka
podman logs guideai-flink-jobmanager
```

## Troubleshooting

### Machine not starting
```bash
# Remove and recreate machine
podman machine stop
podman machine rm
podman machine init --cpus 4 --memory 4096 --disk-size 50
podman machine start
```

### Port conflicts
```bash
# Check port bindings
podman ps --format "{{.Names}}: {{.Ports}}"

# Kill conflicting processes
lsof -ti :9092 | xargs kill -9  # Kafka
lsof -ti :8081 | xargs kill -9  # Flink
```

### Volume mount issues
```bash
# Podman may require explicit volume permissions
podman volume ls
podman volume inspect guideai_kafka-data

# Recreate volumes if needed
podman-compose -f docker-compose.telemetry.yml down -v
podman-compose -f docker-compose.telemetry.yml up -d
```

### Network issues
```bash
# Check networks
podman network ls
podman network inspect guideai-telemetry

# Recreate network
podman network rm guideai-telemetry
podman network create guideai-telemetry
```

## Performance Tips

### Resource Allocation
```bash
# Adjust machine resources for better performance
podman machine stop
podman machine set --cpus 6 --memory 8192
podman machine start
```

### Cleanup
```bash
# Remove unused images
podman image prune -a

# Remove unused volumes
podman volume prune

# System cleanup
podman system prune --all --volumes
```

## Monitoring

### Podman Desktop UI
- Open Podman Desktop app
- View containers, images, volumes
- Monitor resource usage
- Check logs graphically

### CLI Monitoring
```bash
# Watch container stats
podman stats

# Follow logs
podman logs -f guideai-kafka

# Inspect container
podman inspect guideai-kafka
```

## Differences from Docker Desktop

| Feature | Docker Desktop | Podman |
|---------|---------------|--------|
| Daemon | Yes (always running) | No (daemonless) |
| Root required | Yes (by default) | No (rootless) |
| GUI | Included | Optional (Podman Desktop) |
| Memory usage | ~2-4 GB idle | ~500 MB idle |
| Compose support | Native | Via podman-compose |
| VM on macOS | Docker Desktop VM | Podman machine |

## Converting Docker Commands

Most Docker commands work with Podman by simply replacing `docker` with `podman`:

```bash
# Docker → Podman
docker ps              → podman ps
docker build           → podman build
docker run             → podman run
docker compose up      → podman-compose up
docker exec            → podman exec
docker logs            → podman logs
```

## Additional Resources

- [Podman Official Docs](https://docs.podman.io/)
- [Podman Desktop](https://podman-desktop.io/)
- [Migration Guide](https://docs.podman.io/en/latest/markdown/podman-compose.1.html)
- [macOS Setup Guide](https://podman.io/getting-started/installation#macos)

## Support

If you encounter issues:
1. Check Podman machine status: `podman machine list`
2. Review logs: `podman logs <container-name>`
3. Consult [`deployment/README.md`](README.md) for general troubleshooting
4. File issue with Podman-specific details
