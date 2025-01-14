import os, argparse
from ngen.config.realization import NgenRealization
from ngen.config.validate import validate_paths
from ngen.config.configurations import Routing
import re
import geopandas
import pandas as pd
from datetime import datetime
import concurrent.futures as cf

def validate_realization(realization_file):
    """
    Validates
    1) Realization files meets pydantic model as defined in ngen-cal
    2) Paths given in file exist
    """
    relative_dir     = os.path.dirname(os.path.dirname(realization_file))

    print(f'Done\nValidating {realization_file}')
    serialized_realization = NgenRealization.parse_file(realization_file)
    serialized_realization.resolve_paths(relative_to=relative_dir)
    val = validate_paths(serialized_realization)
    for jval in val:
        model = jval.model
        if isinstance(model,Routing): # Allow config path for routing to not exist
            pass
        else:
            raise Exception(f'{val[0].value} does not exist!')
    
    return serialized_realization, relative_dir

def validate_forcings(forcing_files, catchments):
    """
    Validates 
    1) forcing file names match realization file description
    2) forcing files exist for each catchment in geojson
    3) forcingg start/end times and interval match realization file
    """
            
    ncatchments = len(catchments)    
    write_int = 5000    
    for j, jcatch in enumerate(catchments):    
        if (j + 1) % write_int or j == ncatchments - 1: 
            print(f'{100*j/ncatchments:.1f}%', end = "\r")
        jid         = re.findall(r'\d+', jcatch)[0]
        pattern     = serialized_realization.global_config.forcing.file_pattern
        jcatch_pattern = pattern.replace('{{id}}',jid)
        compiled       = re.compile(jcatch_pattern)      

        jfile = forcing_files[j]     
        assert bool(compiled.match(jfile)), f"{jcatch} -> Forcing file {jfile} does not match pattern specified {pattern}"            

        if j == 0:
            start_time = serialized_realization.time.start_time
            end_time   = serialized_realization.time.end_time
            dt_s = serialized_realization.time.output_interval
            full_path = os.path.join(forcing_dir,forcing_files[0])
            df = pd.read_csv(full_path)
            forcings_start = datetime.strptime(df['time'].iloc[0],'%Y-%m-%d %H:%M:%S')
            forcings_end   = datetime.strptime(df['time'].iloc[-1],'%Y-%m-%d %H:%M:%S')
            dt_forcings_s = (forcings_end - forcings_start).total_seconds() / (len(df['time']) - 1)
            assert start_time == forcings_start, f"Realization start time {start_time} does not match forcing start time {forcings_start}"
            assert end_time == forcings_end, f"Realization end time {end_time} does not match forcing end time {forcings_end}"
            assert dt_s == dt_forcings_s, f"Realization output_interval {dt_s} does not match forcing time axis {dt_forcings_s}"

def validate_data_dir(data_dir):

    forcing_files    = []
    catchment_file   = None
    nexus_file       = None
    realization_file = None
    geopackage_file  = None
    for path, _, files in os.walk(data_dir):
        for jfile in files:
            jfile_path = os.path.join(path,jfile)
            if jfile_path.find('config') >= 0:
                if jfile_path.find('catchments') >= 0:
                    if catchment_file is None:                         
                        catchment_file = jfile_path
                    else: 
                        raise Exception('This run directory contains more than a single catchment file, remove all but one.')
                if jfile_path.find('nexus') >= 0: 
                    if nexus_file is None: 
                        nexus_file = jfile_path
                    else: 
                        raise Exception('This run directory contains more than a single nexus file, remove all but one.')
                if jfile_path.find('realization') >= 0: 
                    if realization_file is None: 
                        realization_file = jfile_path
                    else: 
                        raise Exception('This run directory contains more than a single realization file, remove all but one.')
                if jfile_path.find('.gpkg') >= 0: 
                    if geopackage_file is None: 
                        geopackage_file = jfile_path
                    else: 
                        raise Exception('This run directory contains more than a single geopackage file, remove all but one.')                    
            if jfile_path.find('forcing') >= 0 and jfile_path.find('forcing_metadata') < 0: 
                forcing_files.append(jfile_path) 

    if not geopackage_file:
        file_list = [catchment_file,nexus_file,realization_file]
    else:
        file_list = [geopackage_file,realization_file]
        if catchment_file or nexus_file: raise Exception('The spatial domain must only be defined with either a geopackage, or catchment/nexus files. Not both.')
    if any([x is None for x in file_list]):
        raise Exception(f'Missing configuration file!')      

    print(f'Configurations found! Retrieving catchment data...')

    catchments     = geopandas.read_file(geopackage_file, layer='divides')
    catchment_list = sorted(list(catchments['divide_id']))

    global serialized_realization
    serialized_realization, relative_dir = validate_realization(realization_file)    

    print(f'Done\nValidating individual catchment forcing paths')
    global forcing_dir
    forcing_dir    = os.path.join(relative_dir,serialized_realization.global_config.forcing.path)
    forcing_files = sorted([x for _,_,x in os.walk(forcing_dir)][0])  

    nprocs = os.cpu_count()
    forcing_files_list = []
    catchment_list_list = []
    realization_file_list = []
    ncatchments = len(catchment_list)
    nper = ncatchments // nprocs
    nleft = ncatchments - (nper * nprocs)
    i = 0
    k = 0
    for _ in range(nprocs):
        realization_file_list.append(realization_file)
        k = nper + i + nleft      
        jfiles = forcing_files[i:k]
        jcatchments = catchment_list[i:k]
        forcing_files_list.append(jfiles)
        catchment_list_list.append(jcatchments)
        i = k
        
    with cf.ProcessPoolExecutor() as pool:
        for results in pool.map(
            validate_forcings,
            forcing_files_list,
            catchment_list_list):
            pass

    print(f'\nNGen run folder is valid\n')        

if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data_dir",
        dest="data_dir", 
        type=str,
        help="Path to the ngen input data folder", 
        required=False
    )
    parser.add_argument(
        "--tarball",
        dest="tarball", 
        type=str, 
        help="Path to tarball to be validated as ngen input data folder", 
        required=False
    )
    args = parser.parse_args()

    if args.data_dir:
        data_dir = args.data_dir
        ii_delete_folder = False
    elif args.tarball:
        data_dir = '/tmp/ngen_data_dir'
        if os.path.exists(data_dir): 
            os.system(f'rm -rf {data_dir}')
        os.mkdir(data_dir)
        os.system(f'tar -xzf {args.tarball} -C {data_dir}')
        ii_delete_folder = True
    elif args.data_dir and args.tarball:
        raise Exception('Must specify either data folder path or tarball path, not both.')
    else:
        raise Exception('No options set!')
    
    assert os.path.exists(data_dir), f"{data_dir} is an invalid directory"

    validate_data_dir(data_dir)

    if ii_delete_folder: os.system('rm -rf /tmp/ngen_data_dir')
