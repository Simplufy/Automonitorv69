import math
import httpx
from typing import Optional, Tuple

# Area code to approximate geographic center mapping for shipping estimation
AREA_CODE_LOCATIONS = {
    # Major metropolitan areas with approximate lat/lon
    '201': (40.7589, -74.0758),  # Northern NJ (Newark area)
    '202': (38.9072, -77.0369),  # Washington DC
    '203': (41.3083, -73.0176),  # Connecticut (Stamford)
    '205': (33.5186, -86.8104),  # Alabama (Birmingham)
    '206': (47.6062, -122.3321), # Washington (Seattle)
    '207': (44.3106, -69.7795),  # Maine (Augusta)
    '208': (43.6150, -116.2023), # Idaho (Boise)
    '209': (37.6391, -120.9969), # California (Stockton)
    '210': (29.4241, -98.4936),  # Texas (San Antonio)
    '212': (40.7128, -74.0060),  # New York (Manhattan)
    '213': (34.0522, -118.2437), # California (Los Angeles)
    '214': (32.7767, -96.7970),  # Texas (Dallas)
    '215': (39.9526, -75.1652),  # Pennsylvania (Philadelphia)
    '216': (41.4993, -81.6944),  # Ohio (Cleveland)
    '217': (39.7817, -89.6501),  # Illinois (Springfield)
    '218': (46.7867, -92.1005),  # Minnesota (Duluth)
    '219': (41.4789, -87.3828),  # Indiana (Gary)
    '224': (42.0883, -87.9806),  # Illinois (Evanston)
    '225': (30.4515, -91.1871),  # Louisiana (Baton Rouge)
    '228': (30.3960, -89.0928),  # Mississippi (Gulfport)
    '229': (31.1580, -84.1557),  # Georgia (Albany)
    '231': (44.2619, -85.4006),  # Michigan (Traverse City)
    '234': (41.0732, -81.5179),  # Ohio (Akron)
    '239': (26.1420, -81.7948),  # Florida (Fort Myers)
    '240': (39.0458, -76.6413),  # Maryland (Frederick)
    '248': (42.5803, -83.1345),  # Michigan (Pontiac)
    '251': (30.6943, -88.0431),  # Alabama (Mobile)
    '252': (35.8582, -77.0558),  # North Carolina (Rocky Mount)
    '253': (47.2529, -122.4443), # Washington (Tacoma)
    '254': (31.0985, -97.3428),  # Texas (Killeen)
    '256': (34.6059, -86.9833),  # Alabama (Huntsville)
    '260': (41.0793, -85.1394),  # Indiana (Fort Wayne)
    '262': (43.0389, -88.2619),  # Wisconsin (Kenosha)
    '267': (40.0094, -75.1333),  # Pennsylvania (Philadelphia)
    '269': (42.2917, -85.5872),  # Michigan (Kalamazoo)
    '270': (37.0431, -88.6781),  # Kentucky (Paducah)
    '276': (36.7098, -82.2735),  # Virginia (Bristol)
    '281': (29.7604, -95.3698),  # Texas (Houston)
    '301': (39.0458, -76.6413),  # Maryland (Frederick)
    '302': (39.7391, -75.5398),  # Delaware (Wilmington)
    '303': (39.7392, -104.9903), # Colorado (Denver)
    '304': (39.2833, -80.6500),  # West Virginia (Bridgeport)
    '305': (25.7617, -80.1918),  # Florida (Miami)
    '307': (41.1400, -104.8197), # Wyoming (Cheyenne)
    '308': (40.9264, -98.3434),  # Nebraska (Grand Island)
    '309': (40.6936, -89.5890),  # Illinois (Peoria)
    '310': (34.0522, -118.2437), # California (Los Angeles)
    '312': (41.8781, -87.6298),  # Illinois (Chicago)
    '313': (42.3314, -83.0458),  # Michigan (Detroit)
    '314': (38.6270, -90.1994),  # Missouri (St. Louis)
    '315': (43.0481, -76.1474),  # New York (Syracuse)
    '316': (37.6872, -97.3301),  # Kansas (Wichita)
    '317': (39.7684, -86.1581),  # Indiana (Indianapolis)
    '318': (32.5252, -93.7502),  # Louisiana (Shreveport)
    '319': (41.6611, -91.5302),  # Iowa (Cedar Rapids)
    '320': (45.5608, -94.6859),  # Minnesota (St. Cloud)
    '321': (28.5383, -80.8414),  # Florida (Melbourne)
    '323': (34.0522, -118.2437), # California (Los Angeles)
    '330': (41.0732, -81.5179),  # Ohio (Akron)
    '331': (41.7586, -88.0855),  # Illinois (Aurora)
    '334': (32.3668, -86.2999),  # Alabama (Montgomery)
    '336': (36.0726, -79.7920),  # North Carolina (Greensboro)
    '337': (30.2241, -92.0198),  # Louisiana (Lafayette)
    '339': (42.3584, -71.0598),  # Massachusetts (Boston)
    '347': (40.6782, -73.9442),  # New York (Brooklyn)
    '351': (42.3584, -71.0598),  # Massachusetts (Boston)
    '352': (29.6516, -82.3248),  # Florida (Gainesville)
    '360': (47.3809, -122.2348), # Washington (Olympia)
    '361': (27.8006, -97.3964),  # Texas (Corpus Christi)
    '386': (29.0380, -81.0998),  # Florida (Daytona Beach)
    '401': (41.8240, -71.4128),  # Rhode Island (Providence)
    '402': (41.2565, -95.9345),  # Nebraska (Omaha)
    '404': (33.7490, -84.3880),  # Georgia (Atlanta)
    '405': (35.4676, -97.5164),  # Oklahoma (Oklahoma City)
    '406': (46.5197, -110.3626), # Montana (Great Falls)
    '407': (28.5383, -81.3792),  # Florida (Orlando)
    '408': (37.3382, -121.8863), # California (San Jose)
    '409': (29.7030, -94.0175),  # Texas (Beaumont)
    '410': (39.2904, -76.6122),  # Maryland (Baltimore)
    '412': (40.4406, -79.9959),  # Pennsylvania (Pittsburgh)
    '413': (42.1015, -72.5898),  # Massachusetts (Springfield)
    '414': (43.0389, -87.9065),  # Wisconsin (Milwaukee)
    '415': (37.7749, -122.4194), # California (San Francisco)
    '417': (37.2090, -93.2923),  # Missouri (Springfield)
    '419': (41.6528, -83.5379),  # Ohio (Toledo)
    '423': (35.0456, -85.3097),  # Tennessee (Chattanooga)
    '424': (34.0522, -118.2437), # California (Los Angeles)
    '425': (47.6205, -122.3493), # Washington (Bellevue)
    '430': (32.5007, -94.7404),  # Texas (Longview)
    '432': (31.9973, -102.0779), # Texas (Midland)
    '434': (37.4316, -78.6569),  # Virginia (Lynchburg)
    '435': (37.6781, -113.0641), # Utah (St. George)
    '440': (41.4993, -81.6944),  # Ohio (Cleveland)
    '443': (39.2904, -76.6122),  # Maryland (Baltimore)
    '458': (46.8772, -96.7898),  # Oregon (Eugene)
    '469': (32.7767, -96.7970),  # Texas (Dallas)
    '470': (33.7490, -84.3880),  # Georgia (Atlanta)
    '475': (41.3083, -73.0176),  # Connecticut (Bridgeport)
    '478': (32.8407, -83.6324),  # Georgia (Macon)
    '479': (35.3859, -94.3985),  # Arkansas (Fort Smith)
    '480': (33.4484, -112.0740), # Arizona (Phoenix)
    '484': (40.3428, -75.9269),  # Pennsylvania (Reading)
    '501': (34.7465, -92.2896),  # Arkansas (Little Rock)
    '502': (38.2527, -85.7585),  # Kentucky (Louisville)
    '503': (45.5152, -122.6784), # Oregon (Portland)
    '504': (29.9511, -90.0715),  # Louisiana (New Orleans)
    '505': (35.0844, -106.6504), # New Mexico (Albuquerque)
    '507': (44.0582, -92.4732),  # Minnesota (Rochester)
    '508': (42.2596, -71.8083),  # Massachusetts (Worcester)
    '509': (47.6587, -117.4260), # Washington (Spokane)
    '510': (37.8044, -122.2712), # California (Oakland)
    '512': (30.2672, -97.7431),  # Texas (Austin)
    '513': (39.1031, -84.5120),  # Ohio (Cincinnati)
    '515': (41.5868, -93.6250),  # Iowa (Des Moines)
    '516': (40.7589, -73.5843),  # New York (Hempstead)
    '517': (42.3314, -84.5555),  # Michigan (Lansing)
    '518': (42.6803, -73.8370),  # New York (Albany)
    '520': (32.2217, -110.9265), # Arizona (Tucson)
    '530': (39.1638, -121.6061), # California (Chico)
    '540': (38.4404, -78.8689),  # Virginia (Harrisonburg)
    '541': (44.0521, -121.3153), # Oregon (Bend)
    '551': (40.7589, -74.0758),  # New Jersey (Newark)
    '559': (36.7378, -119.7871), # California (Fresno)
    '561': (26.7153, -80.0534),  # Florida (West Palm Beach)
    '562': (33.7701, -118.1937), # California (Long Beach)
    '563': (41.5868, -90.5776),  # Iowa (Davenport)
    '564': (47.6062, -122.3321), # Washington (Seattle)
    '567': (41.6528, -83.5379),  # Ohio (Toledo)
    '570': (41.2033, -75.8816),  # Pennsylvania (Scranton)
    '571': (38.9072, -77.0369),  # Virginia (Arlington)
    '573': (38.9517, -92.3341),  # Missouri (Columbia)
    '574': (41.6764, -86.2520),  # Indiana (South Bend)
    '575': (35.0844, -106.6504), # New Mexico (Albuquerque)
    '580': (34.6037, -98.4034),  # Oklahoma (Lawton)
    '585': (43.1566, -77.6088),  # New York (Rochester)
    '586': (42.6064, -82.9193),  # Michigan (Warren)
    '601': (32.2988, -90.1848),  # Mississippi (Jackson)
    '602': (33.4484, -112.0740), # Arizona (Phoenix)
    '603': (43.2081, -71.5376),  # New Hampshire (Manchester)
    '605': (44.0805, -103.2310), # South Dakota (Rapid City)
    '606': (37.1526, -83.7734),  # Kentucky (Hazard)
    '607': (42.4430, -76.5019),  # New York (Elmira)
    '608': (43.0731, -89.4012),  # Wisconsin (Madison)
    '609': (40.0583, -74.4057),  # New Jersey (Trenton)
    '610': (40.3428, -75.9269),  # Pennsylvania (Reading)
    '612': (44.9778, -93.2650),  # Minnesota (Minneapolis)
    '614': (39.9612, -82.9988),  # Ohio (Columbus)
    '615': (36.1627, -86.7816),  # Tennessee (Nashville)
    '616': (42.9634, -85.6681),  # Michigan (Grand Rapids)
    '617': (42.3584, -71.0598),  # Massachusetts (Boston)
    '618': (38.6270, -89.2023),  # Illinois (Belleville)
    '619': (32.7157, -117.1611), # California (San Diego)
    '620': (37.6872, -99.1013),  # Kansas (Dodge City)
    '623': (33.4484, -112.0740), # Arizona (Phoenix)
    '626': (34.1064, -117.5931), # California (Pasadena)
    '628': (37.7749, -122.4194), # California (San Francisco)
    '629': (36.1627, -86.7816),  # Tennessee (Nashville)
    '630': (41.7586, -88.0855),  # Illinois (Aurora)
    '631': (40.8176, -73.1365),  # New York (Islip)
    '636': (38.7442, -90.3816),  # Missouri (O'Fallon)
    '641': (42.0308, -93.6091),  # Iowa (Mason City)
    '646': (40.7128, -74.0060),  # New York (Manhattan)
    '650': (37.4419, -122.1430), # California (Palo Alto)
    '651': (44.9537, -93.0900),  # Minnesota (St. Paul)
    '657': (33.8366, -117.9143), # California (Anaheim)
    '660': (39.7391, -93.1796),  # Missouri (Sedalia)
    '661': (34.5794, -118.1165), # California (Lancaster)
    '662': (33.4735, -88.8381),  # Mississippi (Tupelo)
    '667': (39.2904, -76.6122),  # Maryland (Baltimore)
    '669': (37.3382, -121.8863), # California (San Jose)
    '678': (33.7490, -84.3880),  # Georgia (Atlanta)
    '682': (32.7355, -97.1081),  # Texas (Arlington)
    '701': (46.8083, -100.7837), # North Dakota (Bismarck)
    '702': (36.1699, -115.1398), # Nevada (Las Vegas)
    '703': (38.9072, -77.0369),  # Virginia (Arlington)
    '704': (35.2271, -80.8431),  # North Carolina (Charlotte)
    '706': (33.9519, -83.3576),  # Georgia (Athens)
    '707': (38.2975, -122.2869), # California (Santa Rosa)
    '708': (41.7586, -87.7040),  # Illinois (Cicero)
    '712': (42.4969, -96.4003),  # Iowa (Sioux City)
    '713': (29.7604, -95.3698),  # Texas (Houston)
    '714': (33.8366, -117.9143), # California (Anaheim)
    '715': (44.9537, -91.4985),  # Wisconsin (Eau Claire)
    '716': (42.8864, -78.8784),  # New York (Buffalo)
    '717': (40.2732, -76.8839),  # Pennsylvania (Harrisburg)
    '718': (40.6782, -73.9442),  # New York (Brooklyn)
    '719': (38.8339, -104.8214), # Colorado (Colorado Springs)
    '720': (39.7392, -104.9903), # Colorado (Denver)
    '724': (40.4406, -79.9959),  # Pennsylvania (Pittsburgh)
    '725': (36.1699, -115.1398), # Nevada (Las Vegas)
    '727': (27.7663, -82.6404),  # Florida (St. Petersburg)
    '731': (35.6145, -88.8140),  # Tennessee (Jackson)
    '732': (40.4173, -74.4097),  # New Jersey (New Brunswick)
    '734': (42.2808, -83.7430),  # Michigan (Ann Arbor)
    '737': (30.2672, -97.7431),  # Texas (Austin)
    '740': (39.3292, -82.1013),  # Ohio (Lancaster)
    '747': (34.1684, -118.6059), # California (Van Nuys)
    '754': (26.1224, -80.1373),  # Florida (Fort Lauderdale)
    '757': (36.8468, -76.2852),  # Virginia (Norfolk)
    '760': (33.2058, -117.2393), # California (Vista)
    '762': (33.7490, -84.3880),  # Georgia (Atlanta)
    '763': (45.1732, -93.3993),  # Minnesota (Plymouth)
    '765': (40.1934, -85.3756),  # Indiana (Anderson)
    '770': (33.7490, -84.3880),  # Georgia (Atlanta)
    '772': (27.3364, -80.3932),  # Florida (Port St. Lucie)
    '773': (41.8781, -87.6298),  # Illinois (Chicago)
    '774': (42.2596, -71.8083),  # Massachusetts (Worcester)
    '775': (39.1638, -119.7674), # Nevada (Reno)
    '781': (42.3584, -71.0598),  # Massachusetts (Boston)
    '785': (39.0473, -95.6890),  # Kansas (Topeka)
    '786': (25.7617, -80.1918),  # Florida (Miami)
    '801': (40.7608, -111.8910), # Utah (Salt Lake City)
    '802': (44.2601, -72.5806),  # Vermont (Montpelier)
    '803': (34.0007, -81.0348),  # South Carolina (Columbia)
    '804': (37.5407, -77.4360),  # Virginia (Richmond)
    '805': (34.4208, -119.6982), # California (Ventura)
    '806': (33.5779, -101.8552), # Texas (Lubbock)
    '808': (21.3099, -157.8581), # Hawaii (Honolulu)
    '810': (42.9634, -83.7430),  # Michigan (Flint)
    '812': (38.9606, -87.3964),  # Indiana (Evansville)
    '813': (27.9506, -82.4572),  # Florida (Tampa)
    '814': (40.4406, -78.3947),  # Pennsylvania (Altoona)
    '815': (42.2711, -89.0940),  # Illinois (Rockford)
    '816': (39.0997, -94.5786),  # Missouri (Kansas City)
    '817': (32.7355, -97.1081),  # Texas (Arlington)
    '818': (34.1684, -118.6059), # California (Van Nuys)
    '828': (35.5951, -82.5515),  # North Carolina (Asheville)
    '830': (29.7030, -98.1245),  # Texas (New Braunfels)
    '831': (36.7783, -121.9573), # California (Salinas)
    '832': (29.7604, -95.3698),  # Texas (Houston)
    '843': (32.7765, -79.9311),  # South Carolina (Charleston)
    '845': (41.7370, -74.1754),  # New York (Middletown)
    '847': (42.0883, -87.9806),  # Illinois (Evanston)
    '848': (40.4173, -74.4097),  # New Jersey (New Brunswick)
    '850': (30.4518, -84.2807),  # Florida (Tallahassee)
    '856': (39.8362, -75.0658),  # New Jersey (Camden)
    '857': (42.3584, -71.0598),  # Massachusetts (Boston)
    '858': (32.7157, -117.1611), # California (San Diego)
    '859': (38.0406, -84.5037),  # Kentucky (Lexington)
    '860': (41.7658, -72.6734),  # Connecticut (Hartford)
    '862': (40.7589, -74.0758),  # New Jersey (Newark)
    '863': (27.4989, -81.4333),  # Florida (Lakeland)
    '864': (34.8526, -82.3940),  # South Carolina (Anderson)
    '865': (35.9606, -83.9207),  # Tennessee (Knoxville)
    '870': (35.8429, -91.2071),  # Arkansas (Jonesboro)
    '872': (41.8781, -87.6298),  # Illinois (Chicago)
    '878': (40.4406, -79.9959),  # Pennsylvania (Pittsburgh)
    '901': (35.1495, -90.0490),  # Tennessee (Memphis)
    '903': (32.3513, -94.9547),  # Texas (Tyler)
    '904': (30.3322, -81.6557),  # Florida (Jacksonville)
    '906': (46.5436, -87.3954),  # Michigan (Marquette)
    '907': (61.2181, -149.9003), # Alaska (Anchorage)
    '908': (40.6723, -74.8451),  # New Jersey (Elizabeth)
    '909': (34.0775, -117.6897), # California (San Bernardino)
    '910': (34.2257, -77.9447),  # North Carolina (Wilmington)
    '912': (32.0835, -81.0998),  # Georgia (Savannah)
    '913': (39.0997, -94.5786),  # Kansas (Kansas City)
    '914': (41.0534, -73.5387),  # New York (White Plains)
    '915': (31.7619, -106.4850), # Texas (El Paso)
    '916': (38.5816, -121.4944), # California (Sacramento)
    '917': (40.7128, -74.0060),  # New York (Manhattan)
    '918': (36.1540, -95.9928),  # Oklahoma (Tulsa)
    '919': (35.7796, -78.6382),  # North Carolina (Raleigh)
    '920': (44.2619, -88.4154),  # Wisconsin (Green Bay)
    '925': (37.9018, -122.0312), # California (Concord)
    '928': (34.5394, -112.4685), # Arizona (Prescott)
    '929': (40.6782, -73.9442),  # New York (Brooklyn)
    '931': (36.1028, -86.4669),  # Tennessee (Clarksville)
    '934': (40.7589, -73.5843),  # New York (Hempstead)
    '936': (30.7266, -95.5539),  # Texas (Huntsville)
    '937': (39.7584, -84.1916),  # Ohio (Dayton)
    '940': (33.2148, -97.1331),  # Texas (Denton)
    '941': (27.3365, -82.5307),  # Florida (Sarasota)
    '947': (42.3314, -83.0458),  # Michigan (Detroit)
    '949': (33.6189, -117.9298), # California (Irvine)
    '951': (33.7175, -116.2023), # California (Riverside)
    '952': (44.8801, -93.4669),  # Minnesota (Bloomington)
    '954': (26.1224, -80.1373),  # Florida (Fort Lauderdale)
    '956': (26.2034, -98.2300),  # Texas (Laredo)
    '959': (41.3083, -73.0176),  # Connecticut (Bridgeport)
    '970': (40.5878, -105.0844), # Colorado (Fort Collins)
    '971': (45.5152, -122.6784), # Oregon (Portland)
    '972': (32.7767, -96.7970),  # Texas (Dallas)
    '973': (40.7589, -74.0758),  # New Jersey (Newark)
    '978': (42.6431, -71.3153),  # Massachusetts (Lowell)
    '979': (29.1338, -96.0722),  # Texas (College Station)
    '980': (35.2271, -80.8431),  # North Carolina (Charlotte)
    '984': (35.7796, -78.6382),  # North Carolina (Raleigh)
    '985': (29.9537, -90.0751),  # Louisiana (Hammond)
    '989': (43.4654, -84.5557),  # Michigan (Saginaw)
}
def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2*math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def extract_area_code_from_phone(phone: str) -> Optional[str]:
    """
    Extract area code from phone number string.
    Handles various formats like: 3802275839, (380) 227-5839, 380-227-5839, etc.
    """
    if not phone:
        return None
    
    # Remove all non-digit characters
    digits = ''.join(filter(str.isdigit, phone))
    
    # If we have 10 digits, first 3 are area code
    if len(digits) == 10:
        return digits[:3]
    
    # If we have 11 digits and starts with 1, next 3 are area code
    if len(digits) == 11 and digits.startswith('1'):
        return digits[1:4]
    
    return None

async def geocode_area_code(area_code: str) -> Optional[Tuple[float, float]]:
    """
    Get approximate coordinates for an area code using our lookup table.
    """
    if area_code in AREA_CODE_LOCATIONS:
        return AREA_CODE_LOCATIONS[area_code]
    return None

async def geocode_location(location: str) -> Optional[Tuple[float, float]]:
    """
    Convert a US zip code or city/state to latitude and longitude coordinates.
    Handles both zip codes (via Zippopotam.us) and city/state (via Nominatim/OpenStreetMap).
    Returns (lat, lon) tuple if successful, None if failed.
    """
    if not location or len(location.strip()) < 2:
        return None
    
    location = location.strip()
    
    try:
        # Try as zip code first if it looks like one (5 digits)
        if location.isdigit() and len(location) == 5:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"https://api.zippopotam.us/us/{location}")
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("places") and len(data["places"]) > 0:
                        place = data["places"][0]
                        lat = float(place["latitude"])
                        lon = float(place["longitude"])
                        return (lat, lon)
        
        # If not a zip code or zip code failed, try as city/state using Nominatim (OpenStreetMap)
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Format the query for Nominatim
            query = f"{location}, United States"
            params = {
                'q': query,
                'format': 'json',
                'limit': 1,
                'countrycodes': 'us'
            }
            
            response = await client.get(
                "https://nominatim.openstreetmap.org/search", 
                params=params,
                headers={'User-Agent': 'AutoProfit/1.0 (Python/httpx)'}
            )
            
            if response.status_code == 200:
                data = response.json()
                if data and len(data) > 0:
                    result = data[0]
                    lat = float(result["lat"])
                    lon = float(result["lon"])
                    return (lat, lon)
            
    except Exception as e:
        # Log the error but don't raise - we'll fallback gracefully
        print(f"Geocoding failed for location {location}: {e}")
    
    return None

# Keep the old function name for backward compatibility
async def geocode_zipcode(zipcode: str) -> Optional[Tuple[float, float]]:
    """Backward compatibility wrapper for geocode_location"""
    return await geocode_location(zipcode)
