# Récupération automatique de la dernière image (AMI) Ubuntu 22.04

data "aws_ami" "ubuntu" {
  most_recent = true
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
  owners = ["099720109477"] # Canonical
}

# Instance EC2 unique placée dans le sous-réseau public A

resource "aws_instance" "app_server" {
  ami                  = data.aws_ami.ubuntu.id
  instance_type        = var.instance_type
  subnet_id            = aws_subnet.public_a.id
  vpc_security_group_ids = [aws_security_group.web.id]

  tags = {
    Name = "${local.name_prefix}ec2-instance"
  }
}

# IP Élastique (IP publique fixe pour l'instance)

resource "aws_eip" "elastic_ip" {
  instance = aws_instance.app_server.id
  domain   = "vpc"

  tags = {
    Name = "${local.name_prefix}eip"
  }
}