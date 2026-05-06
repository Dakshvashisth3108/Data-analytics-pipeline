.PHONY: up down restart logs topics produce bronze silver gold dashboard

up:
	docker compose up -d

down:
	docker compose down

restart:
	docker compose restart

logs:
	docker compose logs -f --tail=100

topics:
	docker exec hcm-kafka kafka-topics --bootstrap-server localhost:9092 \
		--create --if-not-exists --partitions 3 --replication-factor 1 --topic hcm.employees
	docker exec hcm-kafka kafka-topics --bootstrap-server localhost:9092 \
		--create --if-not-exists --partitions 3 --replication-factor 1 --topic hcm.attendance
	docker exec hcm-kafka kafka-topics --bootstrap-server localhost:9092 \
		--create --if-not-exists --partitions 3 --replication-factor 1 --topic hcm.performance
	docker exec hcm-kafka kafka-topics --bootstrap-server localhost:9092 \
		--create --if-not-exists --partitions 3 --replication-factor 1 --topic hcm.recruitment
