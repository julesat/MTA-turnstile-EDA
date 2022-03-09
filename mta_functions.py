import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt


city = gpd.read_file("./bike_routes/bike_routes.geojson")


def clean_station_cols(df):
    """
    Rename columns from initial MTA dataset for convenience.
    """

    df = df[['Station ID', 'Complex ID', 'GTFS Stop ID', 'Stop Name', 'Borough', 'Daytime Routes',
             'GTFS Latitude', 'GTFS Longitude']]
     
    df = df.rename(columns={'Station ID': 'station_id',
                            'Complex ID': 'complex_id',
                            'GTFS Stop ID': 'gtfs_id',
                            'Stop Name': 'ref_station_name',
                            'Borough': 'borough',
                            'Daytime Routes': 'routes',
                            'GTFS Latitude': 'lat',
                            'GTFS Longitude': 'long'
                            })
    return df


def load_citibike_sites():
    """
    Retrieving Citibike trip data from a sample month, August 2021, and returning unique stations coordinates from trip start and endpoints.

    Returns: Geopandas dataframe of station names and coordinates 
    """
    citibike_data = pd.read_csv('./202108-citibike-tripdata.csv', low_memory=False)
    start_cols = ['start_station_name', 'start_lat', 'start_lng']
    end_cols = ['end_station_name', 'end_lat', 'end_lng']
    new_cols = ['_'.join(col.split('_')[1:]) for col in start_cols]

    df1 = citibike_data[start_cols].rename(columns={x:y for x,y in zip(start_cols, new_cols)})
    df2 = citibike_data[end_cols].rename(columns={x:y for x,y in zip(end_cols, new_cols)})

    df = df1.append(df2, ignore_index=False).drop_duplicates(subset='station_name')

    citibike_gdf = gpd.GeoDataFrame(df,
                                    geometry=gpd.points_from_xy(df.lng,
                                                                df.lat),
                                    crs="EPSG:4326")
    # excluding Jersey City stations
    citibike_spots = citibike_gdf[citibike_gdf['lng'] > -74.02]

    return citibike_spots


def map_nyc_citibike_docks(geo_df, color='lightseagreen', alpha=0.4):
    """
    Plot NYC citibike stations as geographical points, overlying bike routes shown as gray lines.
    color: color of station markers
    alpha: transparency of bike route lines 

    Returns: axis of plot
    """
    fig = plt.figure(num=None, figsize=(14, 10), dpi=80, facecolor='w', edgecolor='k')
    ax = plt.axes()

    # plot bike routes
    city.plot(ax=ax, alpha=alpha, edgecolor="black", facecolor="white", linewidth=1, label='Bike lanes')

    # plot dock locations
    geo_df['geometry'].plot(ax=ax, facecolor=color, marker='.', markersize=14, label='Current bike docks')

    plt.xlim([-74.05, -73.65])
    plt.ylim([40.54, 40.92])
    plt.tick_params(left=False,
                    bottom=False,
                    labelleft=False,
                    labelbottom=False)
    plt.legend(frameon=False)
    return ax


def add_turnstile_cols(df):
    """
    Feature engineering for MTA turnstile data.

    Returns: updated Pandas dataframe
    """

    df.columns = df.columns.str.strip().str.lower()
    
    # create a new ID column to replace unique combinations of C/A, UNIT, SCP and STATION

    df['id'] = df['c/a'] + df['unit'] + df['scp']
    df['id'] = df['id'].str.replace('-', '')
    df.drop(['c/a', 'unit', 'scp', 'division', 'desc'], axis=1, inplace=True)

    # add columns in datetime format

    df['datetime'] = pd.to_datetime(df.date + ' ' + df.time)
    df['weekday'] = df['datetime'].dt.dayofweek

    # add columns showing the differences in entries/exits (at each turnstile) between each timepoint and the previous one

    df.sort_values(['id', 'datetime'], inplace=True)
    df[['prev_dt', 'prev_entries', 'prev_exits']] = (df.groupby(['id'])[['datetime', 'entries', 'exits']]
                                                     .apply(lambda grp: grp.shift(1)))

    df['time_diff'] = (df['datetime'] - df['prev_dt']).apply(lambda x: x.total_seconds() / 3600)
    df['entries_diff'] = df['entries'] - df['prev_entries']
    df['exits_diff'] = df['exits'] - df['prev_exits']
    df['foot_traffic'] = df['entries_diff'] + df['exits_diff']

    # add an indicator of station size: number of turnstiles

    num_units = df[['id', 'station']].drop_duplicates().groupby('station').count()['id']
    df = df.merge(num_units, left_on='station', right_index=True).rename(columns={'id_x': 'id',
                                                                                  'id_y': 'num_units'})

    return df

def format_station_names(df, column):
    """
    Removing abbreviations/terms that may be found in one data source but not the other.
    """
    df[column] = df[column].str.replace('-', ' ').str.replace('.', '').str.replace('/', ' ')
    df[column] = df[column].str.replace(r'(?<![0-9]\s)\b(BLVD|AVE|AV|LN|ST|PLAZA|PLZ)\b', '')
    df[column] = df[column].str.replace(r'[ ]{2,}', ' ').str.strip()
    return df


def clean_ts_station_duplicates(df):
    """
    For stations that match multiple reference names, choose the option with matching route information.
    In a few cases, it made more sense to drop or combine multiple stations.
    """
    df = df[~df.station_id.isin([45, 108])]

    df = df.drop(
        df[
            (df.ref_station_name == 'NEWKIRK PLAZA') & (df.ts_station_name == 'NEWKIRK AV')
            | (df.ref_station_name == 'NEWKIRK AV') & (df.ts_station_name == 'NEWKIRK PLAZA')
            | (df.ref_station_name == 'ROCKAWAY BLVD') & (df.ts_station_name == 'ROCKAWAY AV')
            | (df.ref_station_name == 'ROCKAWAY AV') & (df.linename == 'C')
            ].index, axis=0)

    # to get rid of remaining duplicate station names, we have to combine the routes/ line info from multiple rows
    dedupe = df.groupby('ref_station_name', as_index=False).agg({'station_id': 'first',
                                                                'gtfs_id': 'first',
                                                                'borough': 'first',
                                                                'routes': ''.join,
                                                                'station': 'first',
                                                                'ts_station_name': 'first',
                                                                'linename': ''.join,
                                                                'lat': 'first',
                                                                'long': 'first'
                                                                })
    dedupe['routes'] = dedupe.routes.apply(lambda x: ''.join(np.unique(sorted(list(x)))))
    dedupe['linename'] = dedupe.linename.apply(lambda x: ''.join(np.unique(sorted(list(x)))))

    return dedupe


def map_nyc_stations(geo_df, ax=None):

    geo_df.plot(ax=ax, edgecolor=geo_df['marker_color'], marker='o', c='None')

    plt.xlim([-74.05, -73.7])
    plt.ylim([40.54, 40.92])
    plt.tick_params(left=False,
                    bottom=False,
                    labelleft=False,
                    labelbottom=False)
