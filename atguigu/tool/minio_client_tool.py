'''
专门封装单例的minio_client,一个项目当中拿到一个client即可,不需要每次都去创建
'''
import json

from minio import Minio

from atguigu.config.config import MinioConfig

minio_client=None

def get_minio_client():
    global minio_client
    if minio_client is None:
        minio_client = Minio(
            endpoint=MinioConfig.minio_endpoint,
            access_key=MinioConfig.minio_access_key,
            secret_key=MinioConfig.minio_secret_key,
            secure=False
            # minio上传文件本质也是在发送http请求,如果这个值是True,它默认要的是https协议
            # minio默认使用的是http协议,所以这里设置为False,请求的时候就使用http协议，就不会报错
            # https的s是SSL证书，如果想要软件能够发送https请求，那在部署软件的时候就需要配置一个SSL证书
        )

        bucket_name = MinioConfig.minio_bucket_name
        # 可以创建桶，一般一个项目就创建一个桶
        if not minio_client.bucket_exists(bucket_name):
            minio_client.make_bucket(bucket_name)

        # 对桶进行权限设置
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": "*"},
                    "Action": ["s3:GetBucketLocation", "s3:ListBucket"],
                    "Resource": f"arn:aws:s3:::{bucket_name}",
                },
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": "*"},
                    "Action": "s3:GetObject",
                    "Resource": f"arn:aws:s3:::{bucket_name}/*",
                },
            ],
        }
        minio_client.set_bucket_policy(bucket_name=bucket_name, policy=json.dumps(policy))

    return minio_client
