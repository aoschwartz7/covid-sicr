"""Functions for getting data needed to fit the models."""

import bs4
from datetime import datetime
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from tqdm import tqdm
from urllib.error import HTTPError


def get_jhu(data_path: str, filter: bool = True) -> None:
    """Gets data from Johns Hopkins CSSEGIS (countries only).

    https://coronavirus.jhu.edu/map.html
    https://github.com/CSSEGISandData/COVID-19

    Args:
        data_path (str): Full path to data directory.

    Returns:
        None
    """
    # Where JHU stores their data
    url_template = ("https://raw.githubusercontent.com/CSSEGISandData/"
                    "COVID-19/master/csse_covid_19_data/"
                    "csse_covid_19_time_series/time_series_covid19_%s_%s.csv")

    # Scrape the data
    dfs = {}
    for region in ['global', 'US']:
        dfs[region] = {}
        for kind in ['confirmed', 'deaths', 'recovered']:
            url = url_template % (kind, region)  # Create the full data URL
            try:
                df = pd.read_csv(url)  # Download the data into a dataframe
            except HTTPError:
                print("Could not download data for %s, %s" % (kind, region))
            else:
                if region == 'global':
                    has_no_province = df['Province/State'].isnull()
                    # Whole countries only; use country name as index
                    df1 = df[has_no_province].set_index('Country/Region')
                    more_dfs = []
                    for country in ['China', 'Canada', 'Australia']:
                        if country == 'Canada' and kind in 'recovered':
                            continue
                        is_c = df['Country/Region'] == country
                        df2 = df[is_c].sum(axis=0, skipna=False).to_frame().T
                        df2['Country/Region'] = country
                        df2 = df2.set_index('Country/Region')
                        more_dfs.append(df2)
                    df = pd.concat([df1] + more_dfs)
                elif region == 'US':
                    # Use state name as index
                    df = df.set_index('Province_State')
                df = df[[x for x in df if '20' in x]]  # Use only data columns
                dfs[region][kind] = df  # Add to dictionary of dataframes

    # Generate a list of countries that have "good" data,
    # according to these criteria:
    good_countries = get_countries(dfs['global'], filter=filter)

    # For each "good" country,
    # reformat and save that data in its own .csv file.
    source = dfs['global']
    for country in tqdm(good_countries, desc='Countries'):  # For each country
        # If we have data in the downloaded JHU files for that country
        if country in source['confirmed'].index:
            df = pd.DataFrame(columns=['dates2', 'cum_cases', 'cum_deaths',
                                       'cum_recover', 'new_cases',
                                       'new_deaths', 'new_recover',
                                       'new_uninfected'])
            df['dates2'] = source['confirmed'].columns

            def fix_dates(x):
                return datetime.strftime(
                            datetime.strptime(x, '%m/%d/%y'), '%m/%d/%y')
            df['dates2'] = df['dates2'].apply(fix_dates)
            df['cum_cases'] = source['confirmed'].loc[country].values
            df['cum_deaths'] = source['deaths'].loc[country].values
            df['cum_recover'] = source['recovered'].loc[country].values
            df[['new_cases', 'new_deaths', 'new_recover']] = \
                df[['cum_cases', 'cum_deaths', 'cum_recover']].diff()
            df['new_uninfected'] = df['new_recover'] + df['new_deaths']
            # Fill NaN with 0 and convert to int
            dfs[country] = df.set_index('dates2').fillna(0).astype(int)
            # Overwrite old data
            dfs[country].to_csv(data_path /
                                ('covidtimeseries_%s.csv' % country))
        else:
            print("No data for %s" % country)


def get_countries(d: pd.DataFrame, filter: bool = True):
    """Get a list of countries from a global dataframe optionally passing
    a quality check

    Args:
        d (pd.DataFrame): Data from JHU tracker (e.g. df['global]).
        filter (bool, optional): Whether to filter by quality criteria.
    """
    if filter:
        has_recoveries = d['recovered'].index[d['recovered'].max(axis=1) > 0]\
                        .tolist()
        enough_cases = d['confirmed'].index[d['confirmed'].diff(axis=1)
                                            .max(axis=1) >= 5].tolist()
        reports_deaths = d['deaths'].index[d['deaths'].max(axis=1) > 0]\
                                    .to_list()
        criteria = list(map(set, [has_recoveries, enough_cases,
                                  reports_deaths]))
        good_countries = list(set.intersection(*criteria))
        print("JHU has %d countries with good data." % len(good_countries))
    else:
        good_countries = list(set(d['confirmed'].index))
        print("JHU has %d countries." % len(good_countries))
    return good_countries


def get_covid_tracking(data_path: str, filter: bool = True,
                       fixes: bool = False) -> None:
    """Gets data from The COVID Tracking Project (US states only).

    https://covidtracking.com

    Args:
        data_path (str): Full path to data directory.

    Returns:
        None
    """
    url = ("https://raw.githubusercontent.com/COVID19Tracking/"
           "covid-tracking-data/master/data/states_daily_4pm_et.csv")
    df_raw = pd.read_csv(url)

    states = df_raw['state'].unique()

    # Fix Michigan
    if fixes:
        michigan_url = ('https://www.michigan.gov/coronavirus/'
                        '0,9753,7-406-98163_98173_99207---,00.html')
        response = requests.get(michigan_url)
        soup = bs4.BeautifulSoup(response.content, features="lxml")
        three_five_index = [x.find_all('td')[0].text for x in
                            soup.find('table').find_all('tr')
                            if x.find_all('td')].index('5-Mar')
        daily_counts = [int(x.find_all('td')[-1].text)
                        for x in soup.find('table').find_all('tr')
                        if x.find_all('td')][:-1]
        cum_counts = np.cumsum(daily_counts)
        cum_counts = cum_counts[three_five_index:]

        def fix_dates_mich(x):
            return datetime.strptime(str(x), '%Y%m%d')

        to_fix = df_raw.loc[df_raw['state'] == 'MI', 'date']\
                       .apply(fix_dates_mich).sort_values().index
        df_raw.loc[to_fix[:len(cum_counts)], 'positive'] = cum_counts

    good = []
    bad = []
    for state in tqdm(states, desc='US States'):  # For each country
        source = df_raw[df_raw['state'] == state]  # Only the given state
        # If we have data in the downloaded file for that state
        if source['recovered'].sum() > 0 or not filter:
            df = pd.DataFrame(columns=['dates2', 'cum_cases', 'cum_deaths',
                                       'cum_recover', 'new_cases',
                                       'new_deaths', 'new_recover',
                                       'new_uninfected'])

            def fix_dates(x):
                return datetime.strftime(datetime.strptime(
                        str(x), '%Y%m%d'), '%m/%d/%y')

            # Convert date format
            df['dates2'] = source['date'].apply(fix_dates)
            df['cum_cases'] = source['positive'].values
            df['cum_deaths'] = source['death'].values
            df['cum_recover'] = source['recovered'].values
            # Fill NaN with 0 and convert to int
            df = df.set_index('dates2').fillna(0).astype(int)
            df = df.sort_index()  # Sort by date ascending
            df[['new_cases', 'new_deaths', 'new_recover']] = \
                df[['cum_cases', 'cum_deaths', 'cum_recover']].diff()
            if df['new_cases'].max() >= 5 or not filter:
                df['new_uninfected'] = df['new_recover'] + df['new_deaths']
                df = df.fillna(0).astype(int)
                # Overwrite old data
                df.to_csv(data_path / ('covidtimeseries_US_%s.csv' % state))
                good.append(state)
            else:
                bad.append(state)
        else:
            bad.append(state)

    if filter:
        print("COVID Tracking had recovery data for %s" % ','.join(good))
        print("COVID Tracking has no recovery data for %s" % ','.join(bad))


def fix_negatives(data_path: str, plot: bool = False) -> None:
    """Fix negative values in daily data.

    The purpose of this script is to fix spurious negative values in new daily
    numbers.  For example, the cumulative total of cases should not go from N
    to a value less than N on a subsequent day.  This script fixes this by
    nulling such data and applying a monotonic spline interpolation in between
    valid days of data.  This only affects a small number of regions.  It
    overwrites the original .csv files produced by the functions above.

    Args:
        data_path (str): Full path to data directory.
        plot (bool): Whether to plot the changes.

    Returns:
        None
    """
    csvs = [x for x in data_path.iterdir() if 'covidtimeseries' in str(x)]
    for csv in tqdm(csvs, desc="Regions"):
        roi = str(csv).split('.')[0].split('_')[-1]
        df = pd.read_csv(csv)
        # Exclude final day because it is often a partial count.
        df = df.iloc[:-1]
        df = fix_neg(df, roi, plot=plot)
        df.to_csv(data_path / (csv.name.split('.')[0]+'.csv'))


def fix_neg(df: pd.DataFrame, roi: str,
            columns: list = ['cases', 'deaths', 'recover'],
            plot: bool = False) -> pd.DataFrame:
    """Used by `fix_negatives` to fix negatives values for a single region.

    This function uses monotonic spline interpolation to make sure that
    cumulative counts are non-decreasing.

    Args:
        df (pd.DataFrame): DataFrame containing data for one region.
        roi (str): One region, e.g 'US_MI' or 'Greece'.
        columns (list, optional): Columns to make non-decreasing.
            Defaults to ['cases', 'deaths', 'recover'].

    Returns:
        pd.DataFrame: [description]
    """
    for c in columns:
        cum = 'cum_%s' % c
        new = 'new_%s' % c
        before = df[cum].copy()
        non_zeros = df[df[new] > 0].index
        has_negs = before.diff().min() < 0
        if len(non_zeros) and has_negs:
            first_non_zero = non_zeros[0]
            maxx = df.loc[first_non_zero, cum].max()
            # Find the bad entries and null the corresponding
            # cumulative column, which are:
            # 1) Cumulative columns which are zero after previously
            # being non-zero
            bad = df.loc[first_non_zero:, cum] == 0
            df.loc[bad[bad].index, cum] = None
            # 2) New daily columns which are negative
            bad = df.loc[first_non_zero:, new] < 0
            df.loc[bad[bad].index, cum] = None
            # Protect against 0 null final value which screws up interpolator
            if np.isnan(df.loc[df.index[-1], cum]):
                df.loc[df.index[-1], cum] = maxx
            # Then run a loop which:
            while True:
                # Interpolates the cumulative column nulls to have
                # monotonic growth
                after = df[cum].interpolate('pchip')
                diff = after.diff()
                if diff.min() < 0:
                    # If there are still negative first-differences at this
                    # point, increase the corresponding cumulative values by 1.
                    neg_index = diff[diff < 0].index
                    df.loc[neg_index, cum] += 1
                else:
                    break
                # Then repeat
            if plot:
                plt.figure()
                plt.plot(df.index, before, label='raw')
                plt.plot(df.index, after, label='fixed')
                r = np.corrcoef(before, after)[0, 1]
                plt.title("%s %s Raw vs Fixed R=%.5g" % (roi, c, r))
                plt.legend()
        else:
            after = before
        # Make sure the first differences are now all non-negative
        assert after.diff().min() >= 0
        # Replace the values
        df[new] = df[cum].diff().fillna(0).astype(int).values
    return df
