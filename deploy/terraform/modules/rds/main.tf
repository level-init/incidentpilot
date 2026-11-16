# Postgres SoR skeleton (O1). Role isolation stays in SQL migrations.

resource "aws_db_subnet_group" "this" {
  name       = "${var.name_prefix}-db"
  subnet_ids = var.subnet_ids

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-db"
  })
}

resource "aws_security_group" "db" {
  name        = "${var.name_prefix}-rds"
  description = "IncidentPilot Postgres access"
  vpc_id      = var.vpc_id

  ingress {
    description = "Postgres from allowed CIDRs"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidr_blocks
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-rds"
  })
}

resource "aws_db_instance" "this" {
  identifier     = "${var.name_prefix}-pg"
  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  allocated_storage     = var.allocated_storage
  max_allocated_storage = var.allocated_storage * 2
  storage_encrypted     = true

  db_name  = var.db_name
  username = var.master_username
  password = var.master_password

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  multi_az               = var.multi_az

  backup_retention_period = 7
  skip_final_snapshot     = true
  deletion_protection     = false

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-pg"
  })
}
