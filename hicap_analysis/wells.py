import numpy as np
from numpy.lib.arraysetops import isin
import pandas as pd
from pandas.core import base
import scipy.special as sps

# define drawdown methods here
def _theis(T,S,time,dist,Q):
    """Calculate Theis drawdown at single location

    Args:
    
    T (float): transmissivity [ft**2/d]
    S (float): storage [unitless]
    time (float, optionally np.array or list): time at which to calculate results [d]
    dist (float, optionall np.array or list): distance at which to calculate results in [ft]
    Q (float): pumping rate (+ is extraction) [ft**3/d]
    
    Returns:
        float (array): drawdown values at input parameter
                        times/distances 
    """
    if isinstance(time, list):
        time = np.array(time)
    if isinstance(dist, list):
        dist = np.array(dist)
    # contruct the well function argument
    u = dist**2. * S / (4. * T * time)
    # calculate and return
    return (Q / (4. * np.pi * T)) * sps.exp1(u)
    
# define stream depletion methods here
def _glover(T,S,time,dist,Q):
    """Calcualte Glover 

    Args:
    T (float): transmissivity [ft**2/d]
    S (float): storage [unitless]
    time (float, optionally np.array or list): time at which to calculate results [d]
    dist (float, optionall np.array or list): distance at which to calculate results in [ft]
    Q (float): pumping rate (+ is extraction) [ft**3/d]


    Returns:
        float (array): depletion values at at input parameter
                        times/distances
    """
    z = np.sqrt((dist**2*S)/(4 * T * time))
    return Q * sps.erfc(z)

def _sdf(T,S,dist,**kwargs):
    """[summary]

    Args:
        T (float): transmissivity [ft**2/d]
        S (float): storage [unitless]
        dist (float, optionall np.array or list): distance at which to calculate results in [ft]
        **kwargs: just included to all for extra values in call
    Returns:
        SDF: Stream depletion factor [d]
    """
    if isinstance(dist, list):
        dist = np.array(dist)
    return dist**2*S/T

def _walton(T,S,dist,time, Q):
    """Calcualte depletion using Watkins (1987) PT-8 BASIC program logic 

    Args:
    T (float): transmissivity [gpd/ft]
    S (float): storage [unitless]
    time (float, optionally np.array or list): time at which to calculate results [d]
    dist (float): distance at which to calculate results in [ft]
    Q (float): pumping rate (+ is extraction) [ft**3/d]


    Returns:
        float (array): depletion values at at input parameter
                        times/distances [CFS]
    """
    if dist > 0:
        G = dist / np.sqrt((0.535 * time * T/S))
    else:
        G = 0
    I = 1 + .0705230784*G + .0422820123*(G**2) + 9.2705272e-03*(G**3)
    J = (I + 1.52014E-04*(G**4) + 2.76567E-04*(G**5)+4.30638E-05*(G**6)) ** 16
    return Q * (1/J) / 3600 / 24

ALL_DD_METHODS = {'theis': _theis}

ALL_DEPL_METHODS = {'glover': _glover,
                    'walton': _walton}

GPM2CFD = 60*24/7.48 # factor to convert from GPM to CFD

class WellResponse():
    """[summary]
    """
    def __init__(self, name, response_type, T, S, dist, Q, stream_apportionment=None, dd_method='Theis', depl_method= 'Walton', theis_time = -9999,
                    depl_pump_time = -99999, depletion_years=5) -> None:
        """[summary]

        Args:
            name ([type]): [description]
            response_type ([type]): [description]
            T ([type]): [description]
            S ([type]): [description]
            dist ([type]): [description]
            Q ([type]): [description]
            stream_apportionment ([type], optional): [description]. Defaults to None.
            dd_method (str, optional): [description]. Defaults to 'Theis'.
            depl_method (str, optional): [description]. Defaults to 'Walton'.
            theis_time (int, optional): [description]. Defaults to -9999.
            depl_pump_time (int, optional): [description]. Defaults to -99999.
            depletion_years (int, optional): [description]. Defaults to 5.
        """
        self._drawdown=None
        self._depletion=None
        self.name = name # name of response (stream, or drawdown response (e.g. assessed well, lake, spring)) evaluated
        self.response_type = response_type # might use this later to sort out which response to return
        self.T = T
        self.T_gpd_ft = T*7.48
        self.S = S
        self.dist = dist
        self.dd_method=dd_method
        self.depl_method=depl_method
        self.depletion_years = depletion_years
        self.theis_time = theis_time
        self.depl_pump_time = depl_pump_time
        self.Q = Q
        self.stream_apportionment = stream_apportionment
        
    def _calc_drawdown(self):
        """calculate drawdown at requested distance and time
        """
        dd_f = ALL_DD_METHODS[self.dd_method.lower()]

        return dd_f(self.T, self.S, self.theis_time, self.dist, self.Q)
        
    def _calc_depletion(self):
        depl_f = ALL_DEPL_METHODS[self.depl_method.lower()]
        
        # initialize containers for time series insitalized with year 0
        self.baseyears = [np.arange(1,365*self.depletion_years + 1)]
        self.imageyears = [np.zeros_like(self.baseyears[0])]
        self.imageyears[0][self.depl_pump_time:] = np.arange(1,len(self.imageyears[0])-self.depl_pump_time+1)

        # construct full time series for each year
        for y in range(1,self.depletion_years):
            # need full pumping and image time series for each year -   
            # with zeros leading previous years
            # baseyears first
            cby = np.zeros_like(self.baseyears[0])
            cby[365*y:] = self.baseyears[0][0:len(self.baseyears[0])-365*y]
            # image years
            ciy = np.zeros_like(self.baseyears[0])
            poffset = 365*y + self.depl_pump_time
            ciy[poffset:] = self.baseyears[0][0:len(ciy)- poffset]
            self.baseyears.append(cby)
            self.imageyears.append(ciy)
            
        depl = np.zeros_like(self.baseyears[0], dtype=float)
        rech = np.zeros_like(self.baseyears[0], dtype=float)
        for cby,ciy in zip(self.baseyears, self.imageyears):
            depl += depl_f(self.T_gpd_ft,self.S,self.dist,cby, self.Q*self.stream_apportionment)
            rech += depl_f(self.T_gpd_ft,self.S,self.dist,ciy, self.Q*self.stream_apportionment)
        
        # NB! --> converting rech to negative values here    
        return depl - rech

    
    @property
    def drawdown(self):
        if self._drawdown is None:
            self._drawdown = self._calc_drawdown()
        return self._drawdown

    @property
    def depletion(self):
        if self._depletion is None:
            self._depletion = self._calc_depletion()
        return self._depletion


class Well():
    """Object to evaluate a pending (or existing, or a couple other possibilities) well with all relevant impacts.
        Preproceessing makes unit conversions and calculates distances as needed
    """

    def __init__(self, well_loc=None, well_status='pending', T=-9999, S=-99999, Q=-99999, depletion_years=5, theis_dd_time=-9999, depl_pump_time=-9999,
         stream_dist=None, drawdown_dist=None, stream_locs=None,  drawdown_locs=None, 
         stream_apportionment=None) -> None:
        """[summary]

        Args:
            well_loc ([type]): [description]
            T ([type]): [description]
            S ([type]): [description]
            Q ([type]): [description]
            depletion_years (int, optional): [description]. Defaults to 4.
            theis_dd_time (int, optional): [description]. Defaults to -9999.
            depl_pump_time (int, optional): [description]. Defaults to -9999.
            stream_dist ([type], optional): [description]. Defaults to None.
            drawdown_dist ([type], optional): [description]. Defaults to None.
            stream_locs ([type], optional): [description]. Defaults to None.
            stream_apportionment ([type], optional): [description]. Defaults to None.
            drawdown_locs ([type], optional): [description]. Defaults to None.
        """
        self._depletion = None
        self._drawdown = None
        self.well_loc=well_loc
        self.stream_locs=stream_locs
        self.drawdown_locs=drawdown_locs # wells at which defining impacts (drawdown)
        self.stream_dist = stream_dist
        self.drawdown_dist = drawdown_dist
        self.T = T
        self.S = S
        self.depletion_years = depletion_years
        self.theis_dd_time = theis_dd_time
        self.depl_pump_time = depl_pump_time
        self.Q = Q
        self.stream_apportionment=stream_apportionment
        self.stream_responses = {} # dict of WellResponse objects for this well with streams
        self.drawdown_responses = {} # dict of WellResponse objects for this well with drawdown responses
        self.well_status = well_status # this is for the well object - later used for aggregation and must be
                # {'existing', 'active', 'pending', 'new_approved', 'inactive' }
        # make sure stream names consistent between dist and apportionment
        assert len(set(self.stream_dist.keys())-set(self.stream_apportionment.keys())) == 0
        self.stream_response_names = list(self.stream_responses.keys())
        self.drawdown_response_names = list(self.drawdown_dist.keys())
        
        # first set all responses up as distances (convert from locations if necessary)
        # TODO: convert locs to distances --> result is a list of distances same lentgh as locs
        # TODO: check dictionary coherence for locations
        if self.stream_dist is None and self.stream_locs:
            raise('converting from locations to distances not implemented yet')
        if self.drawdown_dist is None and self.well_loc:
            raise('converting from locations to distances not implemented yet')


        # now make all the WellResponse objects
        # first for streams
        for cs, (cname, cdist) in enumerate(self.stream_dist.items()):
            self.stream_responses[cs+1] = WellResponse(cname, 'stream', T=self.T, S=self.S, dist=cdist, depl_pump_time =self.depl_pump_time, 
                                Q=self.Q, stream_apportionment=self.stream_apportionment[cname], depl_method='walton')

        # next for drawdown responses
        # TODO: sort out the idea that can only have a single muni well per pumping well with this formulation. should make more flexible
        for cw, (cname,cdist) in enumerate(self.drawdown_dist.items()):
            self.drawdown_responses[cw+1] = WellResponse(cname, 'well', T=self.T, S=self.S, dist=cdist, theis_time=self.theis_dd_time, 
                                Q=self.Q, dd_method='theis', depletion_years=self.depletion_years)        
        
    @property
    def drawdown(self):
        if self._drawdown is None:
            self._drawdown = {}
            for cw, cwob in self.drawdown_responses.items():
                self._drawdown[cwob.name] = cwob.drawdown
        return self._drawdown

    @property
    def depletion(self):
        if self._depletion is None:
            self._depletion = {}
            for cs, cwob in self.stream_responses.items():
                self._depletion[cwob.name] = cwob.depletion
        return self._depletion