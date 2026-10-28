output "delivery_role_arn" {
  value = aws_iam_role.delivery.arn
}
output "ecr_repository_name" {
  value = aws_ecr_repository.app.name
}
output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}
output "data_bucket" {
  value = aws_s3_bucket.data.id
}
output "service_arn" {
  value = var.enable_service ? aws_ecs_express_gateway_service.app[0].service_arn : null
}
output "ingress_paths" {
  value = var.enable_service ? aws_ecs_express_gateway_service.app[0].ingress_paths : null
}
