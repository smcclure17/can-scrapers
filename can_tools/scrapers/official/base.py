import textwrap
from typing import Any, Optional, Union, Dict

import pandas as pd
import requests

from can_tools.scrapers import InsertWithTempTableMixin
from can_tools.scrapers.base import DatasetBase


class StateDashboard(DatasetBase, InsertWithTempTableMixin):
    """
    Definition of common parameters and values for scraping a State Dashbaord

    Attributes
    ----------

    table_name: str = "covid_official"
        Name of database table to insert into
    pk: str = '("vintage", "dt", "location", "variable_id", "demographic_id")'
        Primary key on database table
    provider = "state"
        Provider here is state
    data_type: str = "covid"
        Data type is set to covid
    has_location: bool
        Must be set by subclasses. True if location code (fips code) appears in data
    state_fips: int
        Must be set by subclasses. The two digit state fips code (as an int)

    """

    table_name: str = "covid_official"
    pk: str = '("vintage", "dt", "location", "variable_id", "demographic_id")'
    provider = "state"
    data_type: str = "covid"
    has_location: bool
    state_fips: int

    # def __init__(self, *args, **kwargs):
    #     super().__init__(*args, **kwargs)
    #     self.putter = InsertWithTempTableMixin()
    #
    # def put(self, connstr: str, df: pd.DataFrame) -> None:
    #     self.putter.put(connstr, df)

    def _insert_query(self, df: pd.DataFrame, table_name: str, temp_name: str, pk: str):
        if self.has_location:
            out = f"""
            INSERT INTO data.{table_name} (
              vintage, dt, location, variable_id, demographic_id, value, provider
            )
            SELECT tt.vintage, tt.dt, tt.location, cv.id as variable_id,
                   cd.id as demographic_id, tt.value, cp.id
            FROM {temp_name} tt
            LEFT JOIN meta.covid_variables cv ON tt.category=cv.category AND tt.measurement=cv.measurement AND tt.unit=cv.unit
            LEFT JOIN data.covid_providers cp ON '{self.provider}'=cp.name
            INNER JOIN meta.covid_demographics cd ON tt.age=cd.age AND tt.race=cd.race AND tt.sex=cd.sex
            ON CONFLICT {pk} DO UPDATE set value = excluded.value
            """
        elif "county" in list(df):
            out = f"""
            INSERT INTO data.{table_name} (
              vintage, dt, location, variable_id, demographic_id, value, provider
            )
            SELECT tt.vintage, tt.dt, loc.location, cv.id as variable_id,
                   cd.id as demographic_id, tt.value, cp.id
            FROM {temp_name} tt
            LEFT JOIN meta.locations loc on tt.county=loc.name
            LEFT JOIN meta.location_type loct on loc.location_type=loct.id
            LEFT JOIN meta.covid_variables cv ON tt.category=cv.category AND tt.measurement=cv.measurement AND tt.unit=cv.unit
            LEFT JOIN data.covid_providers cp ON '{self.provider}'=cp.name
            INNER JOIN meta.covid_demographics cd ON tt.age=cd.age AND tt.race=cd.race AND tt.sex=cd.sex
            WHERE (loc.state = LPAD({self.state_fips}::TEXT, 2, '0')) AND
                  (loct.name = 'county')
            ON CONFLICT {pk} DO UPDATE SET value = excluded.value
            """
        else:
            msg = "None of the expected geographies were included in"
            msg += " the insert DataFrame"
            raise ValueError(msg)

        return textwrap.dedent(out)


class CountyDashboard(StateDashboard):
    """
    Parent class for scrapers working directly with County dashbaards

    See `StateDashbaord` for more information
    """

    provider: str = "county"


class ArcGIS(StateDashboard):
    """
    Parent class for extracting data from an ArcGIS dashbaord

    Must define class variables:

    * `ARCGIS_ID`
    * `FIPS`

    in order to use this class
    """

    ARCGIS_ID: str

    def __init__(self, params: Optional[Dict[str, Union[int, str]]] = None):
        super(ArcGIS, self).__init__()

        # Default parameter values
        if params is None:
            params: Dict[str, Union[int, str]] = {
                "f": "json",
                "where": "1=1",
                "outFields": "*",
                "returnGeometry": "false",
            }

        self.params = params

    def _esri_ts_to_dt(self, ts: int) -> pd.Timestamp:
        """Convert unix timestamp from ArcGIS to pandas Timestamp"""
        return pd.Timestamp.fromtimestamp(ts / 1000).normalize()

    def arcgis_query_url(self, service: str, sheet: Union[str, int], srvid: str) -> str:
        """
        Construct the arcgis query url given service, sheet, and srvid

        The correct value should be found by inspecting the network tab of the
        browser's developer tools

        Parameters
        ----------
        service : str
            The name of an argcis service
        sheet : Union[str,int]
            The sheet number containing the data of interest
        srvid : str
            The server id hosting the desired service

        Returns
        -------
        url: str
            The url pointing to the ArcGIS resource to be collected

        """
        out = f"https://services{srvid}.arcgis.com/{self.ARCGIS_ID}/"
        out += f"ArcGIS/rest/services/{service}/FeatureServer/{sheet}/query"

        return out

    def get_res_json(
        self, service: str, sheet: Union[str, int], srvid: str, params: Dict[str, Any]
    ) -> dict:
        """
        Execute request and return response json as dict
        Parameters
        ----------
        service, sheet, srvid :
            See `arcgis_query_url` method
        params : dict
            A dictionary of additional parameters to pass as the `params` argument
            to the `requests.get` method. These are turned into http query
            parameters by requests

        Returns
        -------
        js: dict
            A dict containing the JSON response from the making the HTTP request

        """
        # Perform actual request
        url = self.arcgis_query_url(service=service, sheet=sheet, srvid=srvid)
        res = requests.get(url, params=params)

        # TODO: add validation here

        return res.json()

    def arcgis_json_to_df(self, res_json: dict) -> pd.DataFrame:
        """
        Parse the json returned from the main HTTP request into a DataFrame
        Parameters
        ----------
        res_json : dict
            Dict representation of JSON response from making HTTP call

        Returns
        -------
        df: pd.DataFrame
            A pandas DataFrame with all data from the attributes field of the
            `res_json["features"]` dict

        """
        df = pd.DataFrame.from_records([x["attributes"] for x in res_json["features"]])

        return df

    def get_single_sheet_to_df(
        self, service: str, sheet: Union[str, int], srvid: str, params: dict
    ) -> pd.DataFrame:
        """
        Obtain all data for a single request to an ArcGIS service

        Note: if there is pagination required, the arguments should be specified in
        `params` and this routine should be called multiple times as in the
        `get_all_sheet_to_df` method

        Parameters
        ----------
        service, sheet, srvid
            See `arcgis_query_url` method for details
        params: dict
            Additional HTTP query parameters to be sent along with http GET request
            to the ArcGIS resource specified by service, sheet and srvid

        Returns
        -------
        df: pd.DataFrame
            A DataFrame containing full contents of the requested ArcGIS sheet

        """

        # Perform actual request
        res_json = self.get_res_json(service, sheet, srvid, params)

        # Turn into a DF
        df = self.arcgis_json_to_df(res_json)

        return df

    def get_all_sheet_to_df(
        self, service: str, sheet: Union[str, int], srvid: str
    ) -> pd.DataFrame:
        """
        Obtain all data in a particular ArcGIS service sheet as a DataFrame

        Often requires dealing with paginated responses
        Parameters
        ----------
        service, sheet, srvid
            See `arcgis_query_url` method for details

        Returns
        -------
        df: pd.DataFrame
            A DataFrame containing full contents of the requested ArcGIS sheet

        """
        # Get a copy so that we don't screw up main parameters
        curr_params = self.params.copy()

        # Get first request and detrmine number of requests that come per
        # response
        res_json = self.get_res_json(service, sheet, srvid, curr_params)
        total_offset = len(res_json["features"])

        # Use first response to create first DataFrame
        _dfs = [self.arcgis_json_to_df(res_json)]
        unbroken_chain = res_json.get("exceededTransferLimit", False)
        while unbroken_chain:
            # Update parameters and make request
            curr_params.update({"resultOffset": total_offset})
            res_json = self.get_res_json(service, sheet, srvid, curr_params)

            # Convert to DataFrame and store in df list
            _df = self.arcgis_json_to_df(res_json)
            _dfs.append(_df)

            total_offset += len(res_json["features"])
            unbroken_chain = res_json.get("exceededTransferLimit", False)

        # Stack these up
        df = pd.concat(_dfs)

        return df


class SODA(StateDashboard):
    """
    TODO fill this in
    Must define class variables:

    * `baseurl`

    in order to use this class
    """

    baseurl: str

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super(SODA, self).__init__()

    def soda_query_url(
        self, data_id: str, resource: str = "resource", ftype: str = "json"
    ) -> str:
        """
        TODO fill this in

        Parameters
        ----------
        data_id :
        resource :
        ftype :

        Returns
        -------

        """
        out = self.baseurl + f"/{resource}/{data_id}.{ftype}"

        return out

    def get_dataset(
        self, data_id: str, resource: str = "resource", ftype: str = "json"
    ) -> pd.DataFrame:
        """
        TODO fill this in

        Parameters
        ----------
        data_id :
        resource :
        ftype :

        Returns
        -------

        """
        url = self.soda_query_url(data_id, resource, ftype)
        res = requests.get(url)

        df = pd.DataFrame(res.json())

        return df