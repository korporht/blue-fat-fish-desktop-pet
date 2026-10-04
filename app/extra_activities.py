"""Finite play sequences assembled from the supplied 10 fps clips."""
ACTIVITY_STATES=('ds_bamboo_copter','ds_sweep','ds_bubble_pop')

def activity_sequences():
    # Start on frame 2 after the two transition frames, as specified by the pack.
    copter=[('ds_bamboo_copter_takeoff',0,25,0),('ds_bamboo_copter_hover',0,12,0),
        ('ds_bamboo_copter_to_fly_left',0,2,0),('ds_bamboo_copter_fly_left',2,12,-2),
        ('ds_bamboo_copter_fly_left',0,12,-2),('ds_bamboo_copter_to_fly_right',0,2,0),
        ('ds_bamboo_copter_fly_right',2,12,2),('ds_bamboo_copter_fly_right',0,12,2),
        ('ds_bamboo_copter_to_hover',0,2,0),('ds_bamboo_copter_hover',2,12,0),
        ('ds_bamboo_copter_land',0,22,0)]
    sweep=[('ds_sweep_start',0,4,0),('ds_sweep_loop',2,16,0),
        ('ds_sweep_loop',0,16,0),('ds_sweep_loop',0,16,0),('ds_sweep_end',0,18,0)]
    return {'ds_bamboo_copter':copter,'ds_sweep':sweep}
