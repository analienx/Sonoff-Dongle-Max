from deploy.analyze_route_health import analyze


def test_clean_window_is_clean():
    report = analyze(["[2026-09-12 12:00:00] info: normal traffic\n"])
    assert report["verdict"] == "CLEAN"
    assert report["hard_total"] == 0
    assert report["route_total"] == 0


def test_route_repair_is_measured_but_not_hard_failure():
    report = analyze(
        [
            '[2026-09-12 12:01:00] info: Received network/route error ROUTE_ERROR_MANY_TO_ONE_ROUTE_FAILURE for "49550".\n',
            '[2026-09-12 12:01:01] info: Received network/route error ROUTE_ERROR_SOURCE_ROUTE_FAILURE for "26647".\n',
            '[2026-09-12 12:01:02] info: Received network/route error ROUTE_ERROR_NON_TREE_LINK_FAILURE for "49550".\n',
        ]
    )
    assert report["verdict"] == "ROUTING_CHURN"
    assert report["hard_total"] == 0
    assert report["route_total"] == 3
    assert report["route_nwk"] == {"49550": 2, "26647": 1}


def test_address_conflict_is_hard_regression_even_with_route_churn():
    report = analyze(
        [
            '[2026-09-12 12:02:00] info: Received network/route error ROUTE_ERROR_MANY_TO_ONE_ROUTE_FAILURE for "23144".\n',
            "[2026-09-12 12:02:01] warning: An ID conflict was detected for network address '25066'. Corresponding devices kicked from the network.\n",
        ]
    )
    assert report["verdict"] == "HARD_REGRESSION"
    assert report["hard"]["address_conflict"] == 1
    assert report["routing"]["many_to_one"] == 1


def test_transport_and_ack_pressure_are_hard():
    report = analyze(
        [
            "[2026-09-12 12:03:00] warning: ASH_OVERFLOW_ERROR=1\n",
            "[2026-09-12 12:03:01] error: MAC_NO_ACK\n",
            "[2026-09-12 12:03:02] error: APS_NO_ACK\n",
            "[2026-09-12 12:03:03] error: ALLOCATE_PACKET_BUFFER_FAILURE\n",
        ]
    )
    assert report["verdict"] == "HARD_REGRESSION"
    assert report["hard_total"] == 4


def test_soft_timeouts_do_not_masquerade_as_ncp_hard_failure():
    report = analyze(
        [
            "[2026-09-12 12:04:00] warning: Failed to ping 'Lamp' (attempt 1/2)\n",
            "[2026-09-12 12:04:10] error: request timed out after 10000ms\n",
        ]
    )
    assert report["verdict"] == "CLEAN"
    assert report["soft"] == {"failed_ping": 1, "timeout": 1}
