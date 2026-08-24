"""Unit tests for setup_helpers helpers (pagination, IAM ensure)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from setup_helpers import (
    _ensure_lambda_function,
    _ensure_role,
    _find_client_by_name,
    _iter_clients,
    invoke_harness_event_stream,
)


class IterClientsTests(unittest.TestCase):
    def test_iter_clients_yields_across_pages(self):
        cog = MagicMock()
        paginator = MagicMock()
        cog.get_paginator.return_value = paginator
        paginator.paginate.return_value = [
            {"UserPoolClients": [{"ClientId": "a", "ClientName": "one"}]},
            {"UserPoolClients": [{"ClientId": "b", "ClientName": "two"}]},
        ]

        clients = list(_iter_clients(cog, "pool-1"))

        self.assertEqual(
            clients,
            [
                {"ClientId": "a", "ClientName": "one"},
                {"ClientId": "b", "ClientName": "two"},
            ],
        )
        cog.get_paginator.assert_called_once_with("list_user_pool_clients")
        paginator.paginate.assert_called_once_with(
            UserPoolId="pool-1",
            PaginationConfig={"PageSize": 60},
        )

    def test_find_client_by_name_uses_later_page(self):
        cog = MagicMock()
        paginator = MagicMock()
        cog.get_paginator.return_value = paginator
        paginator.paginate.return_value = [
            {"UserPoolClients": [{"ClientId": "a", "ClientName": "other"}]},
            {"UserPoolClients": [{"ClientId": "b", "ClientName": "wanted"}]},
        ]
        cog.describe_user_pool_client.return_value = {"UserPoolClient": {"ClientId": "b", "ClientSecret": "secret"}}

        client_id, client_secret = _find_client_by_name(cog, "pool-1", "wanted")

        self.assertEqual((client_id, client_secret), ("b", "secret"))
        cog.describe_user_pool_client.assert_called_once_with(
            UserPoolId="pool-1",
            ClientId="b",
        )


class EnsureRoleTests(unittest.TestCase):
    def test_create_returns_new_arn(self):
        iam = MagicMock()
        iam.create_role.return_value = {"Role": {"Arn": "arn:aws:iam::1:role/r"}}

        arn = _ensure_role(iam, "r", '{"Version":"2012-10-17"}')

        self.assertEqual(arn, "arn:aws:iam::1:role/r")
        iam.update_assume_role_policy.assert_not_called()

    def test_existing_role_updates_trust_policy(self):
        iam = MagicMock()
        iam.exceptions.EntityAlreadyExistsException = type("EntityAlreadyExistsException", (Exception,), {})
        iam.create_role.side_effect = iam.exceptions.EntityAlreadyExistsException()
        iam.get_role.return_value = {"Role": {"Arn": "arn:aws:iam::1:role/r"}}
        trust = '{"Version":"2012-10-17","Statement":[]}'

        arn = _ensure_role(iam, "r", trust)

        self.assertEqual(arn, "arn:aws:iam::1:role/r")
        iam.update_assume_role_policy.assert_called_once_with(
            RoleName="r",
            PolicyDocument=trust,
        )


class EnsureLambdaFunctionTests(unittest.TestCase):
    def test_existing_function_updates_code(self):
        lam = MagicMock()
        lam.get_function.return_value = {"Configuration": {"FunctionArn": "arn:aws:lambda:us-west-2:1:function:fn"}}
        zip_bytes = b"zip"

        arn = _ensure_lambda_function(lam, "fn", "arn:aws:iam::1:role/r", zip_bytes)

        self.assertEqual(arn, "arn:aws:lambda:us-west-2:1:function:fn")
        lam.update_function_code.assert_called_once_with(FunctionName="fn", ZipFile=zip_bytes)
        lam.create_function.assert_not_called()

    def test_missing_function_creates(self):
        lam = MagicMock()
        lam.exceptions.ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        lam.get_function.side_effect = lam.exceptions.ResourceNotFoundException()
        lam.create_function.return_value = {"FunctionArn": "arn:aws:lambda:us-west-2:1:function:fn"}
        zip_bytes = b"zip"

        with patch("setup_helpers.time.sleep"):
            arn = _ensure_lambda_function(lam, "fn", "arn:aws:iam::1:role/r", zip_bytes)

        self.assertEqual(arn, "arn:aws:lambda:us-west-2:1:function:fn")
        lam.update_function_code.assert_not_called()
        lam.create_function.assert_called_once()
        self.assertEqual(lam.create_function.call_args.kwargs["Code"], {"ZipFile": zip_bytes})


class InvokeHarnessEventStreamTests(unittest.TestCase):
    def test_empty_body_yields_no_events(self):
        events = list(invoke_harness_event_stream(b"", region="us-west-2"))
        self.assertEqual(events, [])

    def test_returns_botocore_event_stream(self):
        from botocore.eventstream import EventStream

        stream = invoke_harness_event_stream(b"", region="us-west-2")
        self.assertIsInstance(stream, EventStream)


if __name__ == "__main__":
    unittest.main()
