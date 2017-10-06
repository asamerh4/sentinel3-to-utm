#!/usr/bin/python
import os, sys, argparse, time, shutil
from osgeo import ogr, osr
from subprocess import call
from subprocess import check_output

#WORK DIR is where this file resides
root_path = os.path.dirname(os.path.realpath(__file__))
os.chdir(root_path)

#INTERNAL VARS
snapBundlePath=root_path+"/snap_bundle/build/"
utmShape = r"utmzone/utmref_overlap_flat.shp"
xfdumanifest = ""
snap_output="snap_output/"
tiles_output="tiles/"
warpInputFileList=[]
noDataValue=""

#RUNTIME VARS
s3InputProductPrefix = os.environ['S3_INPUT_PRODUCT_PREFIX']
s3OutputProductPrefix = os.environ['S3_OUTPUT_PRODUCT_PREFIX']
s3productInfoPrefix = os.environ['S3_PRODUCT_INFO_PREFIX']

if not os.path.exists(root_path+"/s3product"):
    os.makedirs("s3product")
if not os.path.exists(root_path+"/snap_output"):
    os.makedirs("snap_output")
if not os.path.exists(root_path+"/tiles"):
    os.makedirs("tiles")

# Check S3 for tiles. if absent -> get product
def checkOrGetProduct(s3InputProductPrefix):
    
    #get productinfo.json for determining L1 Product Name
    s3InfoCall='''aws --endpoint-url https://obs.eu-de.otc.t-systems.com \
      s3 cp {s3InputProductPrefix}productinfo.json s3product/'''.format(
        s3InputProductPrefix=s3InputProductPrefix
        )
        #TODO: exception handling (check_call)
    call(s3InfoCall, shell=True)
    for line in open("s3product/productinfo.json"):
        productName = line.replace(s3productInfoPrefix, "").rstrip()

    #Look if product-name already registered in tile-bucket.
    s3checkCall="""aws --endpoint-url https://obs.eu-de.otc.t-systems.com \
      s3api list-objects \
      --bucket sentinel3-tiles \
      --prefix products | \
      jq '.Contents[].Key | select(. | contains("{productName}"))'""".format(
        productName=productName
        )
    #exit if product already registered in tiles-bucket
    check = check_output(s3checkCall, shell=True)
    if productName in check:
        print "\n**TILES of : "+productName+" ALREADY REGISTERED & GENERATED...exiting."
        cleanup()
        sys.exit(0)
    
    s3SyncCall='''aws --endpoint-url https://obs.eu-de.otc.t-systems.com \
      s3 sync {s3InputProductPrefix} s3product/{productName}/'''.format(
        s3InputProductPrefix=s3InputProductPrefix,
        productName=productName
        )
        #TODO: exception handling (check_call)
    call(s3SyncCall, shell=True)
    xfdumanifest = "s3product/"+productName+"/xfdumanifest.xml"
    productInfo = []
    productInfo.append(productName) #->[0] is product name
    productInfo.append(xfdumanifest)#->[1] is path to xfdumanifest
    return productInfo

def projectSelectedBands(xfdumanifest):
    with open('reproject_graph.xml.template', 'r') as graph_file_template:
        graph = graph_file_template.read().format(
          xfdumanifest=root_path+"/"+xfdumanifest,
          snap_output=snap_output
        )

    with open('reproject_graph.xml', 'w') as graph_file:
        graph_file.write(graph)
    
    snapCall='''java -cp "{snapBundlePath}*" \
      -Dsnap.mainClass=org.esa.snap.core.gpf.main.GPT \
      -Djava.library.path="{snapBundlePath}" \
      -Dsnap.home="{snapBundlePath}" \
      -Xmx4G org.esa.snap.runtime.Launcher \
      {graph}'''.format(
        snapBundlePath=snapBundlePath,
        graph="reproject_graph.xml"
        )
        #TODO: exception handling (check_call)
    call(snapCall, shell=True)

    for file in os.listdir(snap_output):
        if file.endswith(".tif"):
            warpInputFileList.append(file)
    os.remove("reproject_graph.xml")
    return warpInputFileList

def getUTMRefTiles(xfdumanifest):
    #use utmref shape   
    shapeSource = ogr.Open(utmShape)
    shapeLayer = shapeSource.GetLayer()
    #create empty geometry collection
    queryColl = ogr.Geometry(ogr.wkbGeometryCollection)
    #parse xfdumanifest.xml for gml-poslist
    for line in open(xfdumanifest):
        if "<gml:posList>" in line:
            posList = line
    #inject poslist to gml-skeleton
    footprintGML = '''<gml:Polygon xmlns:gml="http://www.opengis.net/gml">
      <gml:exterior>
        <gml:LinearRing>
          {posList}
        </gml:LinearRing>
      </gml:exterior>
    </gml:Polygon>'''.format(posList = posList) 
    
    #define source-srs and target srs
    s_srs = osr.SpatialReference()
    #gml source has flipped lat lon values
    s_srs.ImportFromProj4("+proj=latlong +datum=WGS84 +axis=neu +wktext")
    t_srs = osr.SpatialReference()
    #target geom shall use "normal" coords
    t_srs.ImportFromProj4("+proj=latlong +datum=WGS84 +axis=enu +wktext")
    #define coordinate transform
    transform = osr.CoordinateTransformation(s_srs, t_srs)
    
    #create ogr geometry from GML
    footprintGeom = ogr.CreateGeometryFromGML(footprintGML)
    #apply transform
    footprintGeom.Transform(transform)
    
    #add transformed geom to collection
    queryColl.AddGeometry(footprintGeom)

    #apply spatial filter & create utm zone/row list
    shapeLayer.SetSpatialFilter(queryColl)
    tiles=[]
    for feature in shapeLayer:
        zone = feature.GetField("UTMREF")
        tiles.append(zone)
    return tiles

def multiWarpToUTM(warpInputFileList, tiles, productName):
    for inFile in warpInputFileList:
        if "S" in inFile:
            noDataValue="-9999"
        else:
            noDataValue="65535"
        for tile in tiles:
            outputPath = tiles_output+tile[:2]+"/"+tile[-1:]+"/"+productName[16:20]+"/"+productName[20:22]+"/"+productName[22:24]+"/"+productName
            if not os.path.exists(outputPath):
                os.makedirs(outputPath)
            warp = '''gdalwarp -overwrite -tr 1000 1000 \
              -wo SKIP_NOSOURCE=YES \
              -crop_to_cutline \
              -t_srs "+proj=utm +zone={zone} +datum=WGS84" \
              -srcnodata {noDataValue} \
              -cutline {utmShape} \
              -cwhere "UTMREF = '{tile}'" \
              {inFile} \
              {outFile}'''.format(
                zone=tile[:2],
                noDataValue=noDataValue,
                utmShape=utmShape,
                tile=tile,
                inFile=snap_output+inFile,
                outFile=outputPath+"/"+inFile
                )
            #TODO: exception handling (check_call)
            call(warp, shell=True)

def syncToS3AndRegister(tiles, productInfo):
    s3UploadCall='''aws --endpoint-url https://obs.eu-de.otc.t-systems.com \
      s3 sync tiles/ {s3OutputProductPrefix}'''.format(
        s3OutputProductPrefix=s3OutputProductPrefix
        )
    call(s3UploadCall, shell=True)
    
    s3RegisterCall='''aws --endpoint-url https://obs.eu-de.otc.t-systems.com \
      s3 cp {xfdu} {s3OutputProductPrefix}products/{productName}/'''.format(
        s3OutputProductPrefix=s3OutputProductPrefix,
        productName=productInfo[0],
        xfdu=productInfo[1]
        )
    call(s3RegisterCall, shell=True)

def cleanup():
    shutil.rmtree("s3product")
    shutil.rmtree("snap_output")
    shutil.rmtree("tiles")

def main():
    print "\n========================================"
    print "sentinel-3 l1 product to utm grid tiling"
    print "========================================"
    #get product from S3
    print "\n**CHECK or GET product from S3"
    productInfo = checkOrGetProduct(s3InputProductPrefix)
    #run snap
    print "\n**PROJECT selected bands using snap"
    warpInputFileList = projectSelectedBands(productInfo[1])
    #get affected UTM tile-id's
    tiles = getUTMRefTiles(productInfo[1])
    #run gdalwarp
    print "\n**run GDALWARP in batch mode for affected utm tiles: "+str(tiles)
    multiWarpToUTM(warpInputFileList, tiles, productInfo[0])
    #Upload/Sync and Register
    print "\n**UPLOAD and REGISTER to S3"
    syncToS3AndRegister(tiles, productInfo)
    cleanup()

if __name__ == "__main__":
    main()


