# Thin wrapper over setup.sh + docker compose. Nothing of substance here;
# the real script is ./setup.sh.

.PHONY: help setup up down restart logs status backup restore shell remove upgrade rollback

help:
	@echo "NBIO Tracker — make targets"
	@echo ""
	@echo "  make setup     run ./setup.sh (interactive bootstrap)"
	@echo "  make up        docker compose up -d"
	@echo "  make down      docker compose down"
	@echo "  make restart   docker compose restart app"
	@echo "  make logs      follow app logs (Ctrl-C to exit)"
	@echo "  make status    docker compose ps"
	@echo "  make backup    force a backup run now"
	@echo "  make restore   show restore instructions"
	@echo "  make upgrade   run ./upgrade.sh (latest tag by default)"
	@echo "  make rollback  run ./upgrade.sh --rollback"
	@echo "  make shell     /bin/sh in the app container"
	@echo "  make remove    run ./remove.sh (uninstall; preserves data by default)"

setup:
	./setup.sh

up:
	docker compose up -d

down:
	docker compose down

restart:
	docker compose restart app

logs:
	docker compose logs -f app

status:
	docker compose ps

backup:
	docker compose exec backup /usr/local/bin/backup.sh

restore:
	@echo "Restore a snapshot via the backup container's helper:"
	@echo ""
	@echo "  docker compose stop app"
	@echo "  docker compose run --rm backup /usr/local/bin/restore.sh \\"
	@echo "      /backups/app-YYYYMMDD-HHMM.db.gz"
	@echo "  docker compose start app"
	@echo ""
	@echo "Or pull from Drive first:"
	@echo "  docker compose run --rm backup /usr/local/bin/restore.sh \\"
	@echo "      remote app-YYYYMMDD-HHMM.db.gz"
	@echo ""
	@echo "See README → Restoring from a backup."

shell:
	docker compose exec app /bin/sh

upgrade:
	./upgrade.sh

rollback:
	./upgrade.sh --rollback

remove:
	./remove.sh
