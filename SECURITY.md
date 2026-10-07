# Security

These tools read local files and, in `osm_fetch.py`, call the public Overpass API. They run no server.

If you find a vulnerability (for example a crafted GeoTIFF or LAZ file that makes a tool execute code or write outside
its output folder), please email **daniel@agoro.games** with the subject "lidar-to-unreal security" instead of opening a
public issue. I aim to answer within 7 days and to credit you in the fix unless you prefer otherwise.
