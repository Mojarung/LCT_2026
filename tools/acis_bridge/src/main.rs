//! Extract R2013+ REGION ACIS alongside a DXF conversion for independent verification.

use acadrust::entities::acis::SabReader;
use acadrust::entities::EntityType;
use acadrust::{DwgReader, DxfWriter};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::File;
use std::io::{BufReader, Read};
use std::path::{Path, PathBuf};

#[derive(Serialize)]
struct RegionSat {
    sab_sha256: String,
    sat: String,
}

#[derive(Serialize)]
struct Sidecar {
    schema: u8,
    engine: &'static str,
    engine_version: &'static str,
    source_sha256: String,
    source_entities: usize,
    source_regions: usize,
    regions: BTreeMap<String, RegionSat>,
}

fn sha256_file(path: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let mut source = BufReader::new(File::open(path)?);
    let mut digest = Sha256::new();
    let mut buffer = [0_u8; 1024 * 1024];
    loop {
        let count = source.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    let source = PathBuf::from(args.next().ok_or("source DWG required")?);
    let output_dxf = PathBuf::from(args.next().ok_or("output DXF required")?);
    let output_sidecar = PathBuf::from(args.next().ok_or("output sidecar required")?);
    if args.next().is_some() {
        return Err("expected exactly three arguments".into());
    }

    let mut reader = DwgReader::from_file(&source)?;
    let drawing = reader.read()?;
    let mut regions = BTreeMap::new();
    let mut source_regions = 0;
    for entity in drawing.entities() {
        let EntityType::Region(region) = entity else {
            continue;
        };
        source_regions += 1;
        let sab = &region.acis_data.sab_data;
        if sab.is_empty() {
            continue;
        }
        let sat = SabReader::read(sab).map_err(|error| {
            format!(
                "REGION {:X}: cannot parse SAB: {error}",
                region.common.handle.value()
            )
        })?;
        let handle = format!("{:X}", region.common.handle.value());
        let value = RegionSat {
            sab_sha256: format!("{:x}", Sha256::digest(sab)),
            sat: sat.to_sat_string(),
        };
        if regions.insert(handle.clone(), value).is_some() {
            return Err(format!("duplicate REGION handle {handle}").into());
        }
    }
    let sidecar = Sidecar {
        schema: 1,
        engine: "acadrust",
        engine_version: "0.5.5",
        source_sha256: sha256_file(&source)?,
        source_entities: drawing.entities().count(),
        source_regions,
        regions,
    };
    DxfWriter::new(&drawing).write_to_file(&output_dxf)?;
    let file = File::create(&output_sidecar)?;
    serde_json::to_writer(file, &sidecar)?;
    println!(
        "regions={} recovered_sab={} entities={}",
        sidecar.source_regions,
        sidecar.regions.len(),
        sidecar.source_entities,
    );
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("green-acis-bridge: {error}");
        std::process::exit(1);
    }
}
