# sentinel3-to-utm
reproject and clip selected bands from Level-1 Sentinel-3 data to UTM/MGRS tiles

## usage

```sh
docker run --rm --net host \
  -e USERDATA_MTD_URL="localhost/user-data" \
  -e S3_INPUT_PRODUCT_PREFIX="s3://sentinel3-rbt/frames/028/0539/2016/12/09/" \
  -e S3_OUTPUT_PRODUCT_PREFIX="s3://sentinel3-tiles/" \
  -e S3_PRODUCT_INFO_PREFIX="s3://sentinel3-rbt/products/" \
asamerh4/sentinel3-to-utm:0e1bd51
```
