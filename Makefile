.PHONY: up down

up:
	docker compose --project-name lyftr up --build --detach --wait --wait-timeout 180

down:
	docker compose --project-name lyftr down --timeout 30
