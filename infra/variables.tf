variable "aws_region" {
  description = "AWS region — eu-north-1 has g6e (L40S 48GB) availability"
  type        = string
  default     = "eu-north-1"
}

variable "instance_type" {
  description = "EC2 GPU instance type (g6e.2xlarge=L40S 48GB+8vCPU, g5.xlarge=A10G 24GB)"
  type        = string
  default     = "g6e.2xlarge"
}

variable "key_pair_name" {
  description = "Name of an existing EC2 key pair for SSH access"
  type        = string
}

variable "my_ip" {
  description = "Your public IP in CIDR notation for SSH access (e.g. 203.0.113.1/32)"
  type        = string
}

variable "hf_token" {
  description = "HuggingFace API token (required for gated models)"
  type        = string
  sensitive   = true
}

variable "llm_gpu_util" {
  description = "GPU memory fraction for LLM (single model swapped at runtime)"
  type        = string
  default     = "0.4"
}

variable "tts_gpu_util" {
  description = "GPU memory fraction for TTS"
  type        = string
  default     = "0.4"
}

variable "root_volume_size" {
  description = "Root EBS volume in GB — vLLM images are ~30GB each"
  type        = number
  default     = 200
}
