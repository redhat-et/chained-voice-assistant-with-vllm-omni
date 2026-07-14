variable "aws_region" {
  description = "AWS region — eu-west-1 has better g5 quota than us regions"
  type        = string
  default     = "eu-west-1"
}

variable "instance_type" {
  description = "EC2 GPU instance type (g5.xlarge=A10G 24GB, g5.2xlarge=A10G 24GB+8vCPU, g6e.xlarge=L40S 48GB)"
  type        = string
  default     = "g5.2xlarge"
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

variable "llm_model" {
  description = "LLM model — use quantized for 24GB GPU, full bf16 for 48GB+"
  type        = string
  default     = "RedHatAI/gemma-3-4b-it-quantized.w4a16"
}

variable "llm_gpu_util" {
  description = "GPU memory fraction for LLM (0.3 for 24GB shared, 0.5+ for 48GB)"
  type        = string
  default     = "0.3"
}

variable "tts_gpu_util" {
  description = "GPU memory fraction for TTS (0.3 for 24GB shared, 0.5+ for 48GB)"
  type        = string
  default     = "0.3"
}

variable "root_volume_size" {
  description = "Root EBS volume in GB — vLLM images are ~30GB each"
  type        = number
  default     = 200
}
