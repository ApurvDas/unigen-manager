import pnp


def test_address_from_instance():
    hfp = r"BTHENUM\{0000111E-0000-1000-8000-00805F9B34FB}_VID&0001004C_PID&201A\8&2538F730&0&020000000013_C00000000"
    assert pnp.address_from_instance(hfp) == "020000000013"
    assert pnp.address_from_instance(r"BTHENUM\{0000111E-0000-1000-8000-00805F9B34FB}_LOCALMFG&0046\7&1&0&000000000000_00000000") is None
    assert pnp.address_from_instance(r"USB\VID_368B&PID_8D81&MI_00\6&28B24B5D&0&0000") is None
