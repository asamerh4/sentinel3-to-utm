import os, argparse
from osgeo import ogr, osr
from subprocess import call

#WORK DIR is where this file resides
root_path = os.path.dirname(os.path.realpath(__file__))
os.chdir(root_path)

#INTERNAL VARS
snapBundlePath="/home/dev1/workspace/snap/snap-s3-bundle/"
utmShape = r"utmzone/utmref_overlap_flat.shp"
xfdumanifest = ""
s3productInfoPrefix = "s3://sentinel3-rbt/products/"
snap_output="snap_output/"
tiles_output="tiles/"
WarpInputFileList=[]
noDataValue=""

#RUNTIME VARS
s3ProductPrefix = "s3://sentinel3-rbt/frames/271/0720/2017/08/26/"

if not os.path.exists(root_path+"/s3product"):
    os.makedirs("s3product")
if not os.path.exists(root_path+"/snap_output"):
    os.makedirs("snap_output")
if not os.path.exists(root_path+"/tiles"):
    os.makedirs("tiles")

def getProduct(s3ProductPrefix):
    
    s3InfoCall='''aws --endpoint-url https://obs.eu-de.otc.t-systems.com \
      s3 cp {s3ProductPrefix}productinfo.json s3product/'''.format(
        s3ProductPrefix=s3ProductPrefix
        )
    call(s3InfoCall, shell=True)
    line0=[]
    for line in open("s3product/productinfo.json"):
        line0.append(line.replace(s3productInfoPrefix, "").rstrip())
    productName=line0[0]
    #print productName

    s3SyncCall='''aws --endpoint-url https://obs.eu-de.otc.t-systems.com \
      s3 sync {s3ProductPrefix} s3product/{productName}/'''.format(
        s3ProductPrefix=s3ProductPrefix,
        productName=productName
        )
    call(s3SyncCall, shell=True)
    xfdumanifest = "s3product/"+productName+"/xfdumanifest.xml"
    print xfdumanifest
    return xfdumanifest

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
    call(snapCall, shell=True)

    for file in os.listdir(snap_output):
        if file.endswith(".tif"):
            WarpInputFileList.append(file)
    os.remove("reproject_graph.xml")
    print ("*BANDS: "+str(WarpInputFileList))


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
    print ("*UTMREF-TILES: "+str(tiles))
    return tiles

def multiWarpToUTM(inFile, noDataValue, xfdumanifest):
    tiles = getUTMRefTiles(xfdumanifest)
    for tile in tiles:
        if not os.path.exists(tiles_output+tile):
            os.makedirs(tiles_output+tile)
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
            outFile=tiles_output+tile+"/"+inFile
            )
        call(warp, shell=True)

def main():
    #get product from S3
    xfdu = getProduct(s3ProductPrefix)
    #run snap
    projectSelectedBands(xfdu)
    #run gdalwarp
    for file in WarpInputFileList:
        if "S" in file:
            noDataValue="-9999"
        else:
            noDataValue="65535"
        multiWarpToUTM(file, noDataValue, xfdu)

if __name__ == "__main__":
    main()


