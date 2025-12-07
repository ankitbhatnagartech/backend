from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

A={
 'architecture':'microservices',
 'traffic':{
   'daily_active_users':10000,
   'api_requests_per_user':50,
   'storage_per_user_mb':10,
   'peak_traffic_multiplier':1.5,
   'growth_rate_yoy':0.1,
   'revenue_per_user_monthly':0,
   'funding_available':0,
   'database': {'type':'rds','read_replicas':0,'backup_enabled':False,'multi_az':False,'cache_type':None,'cache_size_gb':0},
   'cdn': {'enabled':False,'provider':'cloudfront','data_transfer_gb':0,'edge_functions':False,'video_streaming':False},
   'messaging': {'enabled':False,'type':'sqs','messages_per_day':0,'retention_days':7,'dlq_enabled':False},
   'security': {'waf_enabled':False,'vpn_enabled':False,'ddos_protection':False,'ssl_certificates':0,'compliance':[],'secrets_manager':False},
   'monitoring': {'provider':'cloudwatch','log_retention_days':7,'apm_enabled':False,'distributed_tracing':False,'alert_channels':0},
   'cicd': {'provider':'github_actions','builds_per_month':100,'container_registry':False,'security_scanning':False,'artifact_storage_gb':0},
   'multi_region': {'enabled':False,'regions':1,'replication_type':'active_passive','cross_region_transfer_gb':0,'rto_minutes':60,'rpo_minutes':60}
 }
}
B={
 'architecture':'microservices',
 'traffic':{
   'daily_active_users':20000,
   'api_requests_per_user':100,
   'storage_per_user_mb':20,
   'peak_traffic_multiplier':2.0,
   'growth_rate_yoy':0.3,
   'revenue_per_user_monthly':0,
   'funding_available':0,
   'database': {'type':'rds','read_replicas':1,'backup_enabled':True,'multi_az':True,'cache_type':'redis','cache_size_gb':2},
   'cdn': {'enabled':True,'provider':'cloudfront','data_transfer_gb':500,'edge_functions':True,'video_streaming':False},
   'messaging': {'enabled':True,'type':'sqs','messages_per_day':10000,'retention_days':7,'dlq_enabled':False},
   'security': {'waf_enabled':True,'vpn_enabled':False,'ddos_protection':False,'ssl_certificates':1,'compliance':['SOC2'],'secrets_manager':True},
   'monitoring': {'provider':'datadog','log_retention_days':30,'apm_enabled':True,'distributed_tracing':True,'alert_channels':3},
   'cicd': {'provider':'github_actions','builds_per_month':500,'container_registry':True,'security_scanning':True,'artifact_storage_gb':50},
   'multi_region': {'enabled':True,'regions':2,'replication_type':'active_active','cross_region_transfer_gb':200,'rto_minutes':30,'rpo_minutes':15}
 }
}

# First request A
r1 = client.post('/estimate', json=A)
print('R1 status', r1.status_code)
print('R1 ETag:', r1.headers.get('etag'))
print('R1 total:', r1.json().get('monthly_cost',{}).get('total'))

# Second request B
r2 = client.post('/estimate', json=B)
print('\nR2 status', r2.status_code)
print('R2 ETag:', r2.headers.get('etag'))
print('R2 total:', r2.json().get('monthly_cost',{}).get('total'))

# Re-send A with If-None-Match header
etag = r1.headers.get('etag')
if etag:
    r3 = client.post('/estimate', json=A, headers={'If-None-Match': etag})
    print('\nR3 status (with If-None-Match):', r3.status_code)
    print('R3 headers:', {k:v for k,v in r3.headers.items() if k.lower() in ['etag','cache-control']})
    if r3.status_code == 304:
        print('304 returned as expected')
    else:
        print('R3 total:', r3.json().get('monthly_cost',{}).get('total'))
else:
    print('No ETag from R1; cannot test If-None-Match')
