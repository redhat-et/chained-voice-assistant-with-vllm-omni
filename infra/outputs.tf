output "public_ip" {
  description = "Elastic IP of the GPU instance"
  value       = aws_eip.gpu.public_ip
}

output "frontend_url" {
  description = "Voice pipeline frontend"
  value       = "http://${aws_eip.gpu.public_ip}:3000"
}

output "ssh_command" {
  description = "SSH into the instance"
  value       = "ssh -i ~/.ssh/${var.key_pair_name}.pem ubuntu@${aws_eip.gpu.public_ip}"
}

output "livekit_url" {
  description = "LiveKit WebSocket endpoint"
  value       = "ws://${aws_eip.gpu.public_ip}:7880"
}

output "setup_log_command" {
  description = "Tail the setup log to monitor boot progress"
  value       = "ssh -i ~/.ssh/${var.key_pair_name}.pem ubuntu@${aws_eip.gpu.public_ip} 'tail -f /var/log/voice-pipeline-setup.log'"
}

output "chrome_insecure_command" {
  description = "Launch Chrome with insecure origin for mic access over HTTP"
  value       = "/Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --user-data-dir=/tmp/chrome-insecure --unsafely-treat-insecure-origin-as-secure=http://${aws_eip.gpu.public_ip}:3000"
}
