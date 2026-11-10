# Security Group spécifique pour la Base de Données (Port 5432)

resource "aws_security_group" "db_sg" {
  name        = "${local.name_prefix}db-sg"
  description = "Autoriser PostgreSQL uniquement depuis le security group web"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "PostgreSQL depuis EC2"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.web.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}db-sg"
  }
}

# Groupe de sous-réseaux pour RDS (utilise les subnets privés)

resource "aws_db_subnet_group" "db_subnet" {
  name       = "workforce-db-subnet-group"
  subnet_ids = [aws_subnet.private_a.id, aws_subnet.private_b.id]

  tags = {
    Name = "Workforce-DB-Subnet-Group"
  }
}

# Instance RDS PostgreSQL dans le sous-réseau privé

resource "aws_db_instance" "postgres" {
  identifier             = "workforce-db"
  engine                 = "postgres"
  engine_version         = "16"
  instance_class         = "db.t3.micro"
  allocated_storage      = 20
  db_name                = "workforce_db"
  username               = "workforce_admin"
  password               = var.db_password
  db_subnet_group_name   = aws_db_subnet_group.db_subnet.name
  vpc_security_group_ids = [aws_security_group.db_sg.id]
  skip_final_snapshot    = true

  tags = {
    Name = "${local.name_prefix}rds-postgres"
  }
}