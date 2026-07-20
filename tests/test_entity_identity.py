import unittest

from sgcc_ha_bridge.entity_identity import (
    account_entity_key,
    legacy_alias_policy,
    mqtt_legacy_action,
    mqtt_remove_legacy_on_cleanup,
)


class EntityIdentityTestCase(unittest.TestCase):
    def test_account_entity_key_requires_full_account_number(self):
        with self.assertRaises(ValueError):
            account_entity_key("0123")
        with self.assertRaises(ValueError):
            account_entity_key("123456789012x")

    def test_authoritative_policy_assigns_only_unique_published_suffixes(self):
        first = "1234567890123"
        colliding = "9876543210123"
        unique = "2222222220456"
        ignored = "3333333330789"

        policy = legacy_alias_policy(
            [first, colliding, unique, ignored],
            published_account_nos=[first, colliding, unique],
            authoritative=True,
        )

        self.assertEqual(policy.ambiguous_suffixes, frozenset({"0123"}))
        self.assertEqual(policy.owners, frozenset({unique}))
        self.assertFalse(policy.allows(first))
        self.assertTrue(policy.allows(unique))
        self.assertFalse(policy.allows(ignored))

    def test_metadata_only_account_blocks_collision_without_becoming_owner(self):
        useful = "1234567890123"
        metadata_only = "9876543210123"
        policy = legacy_alias_policy(
            [useful, metadata_only],
            published_account_nos=[useful],
            authoritative=True,
        )

        self.assertEqual(policy.owners, frozenset())
        self.assertEqual(policy.ambiguous_suffixes, frozenset({"0123"}))
        self.assertEqual(mqtt_legacy_action("compat", useful, policy), "remove")
        self.assertFalse(policy.allows(metadata_only))

        account_no = "1234567890123"
        policy = legacy_alias_policy([account_no], authoritative=False)

        for mode in ("compat", "off", "cleanup"):
            self.assertEqual(mqtt_legacy_action(mode, account_no, policy), "none")
            self.assertFalse(mqtt_remove_legacy_on_cleanup(mode, account_no, policy))

    def test_legacy_actions_follow_mode_and_collision_policy(self):
        unique = "1234567890456"
        first = "1234567890123"
        colliding = "9876543210123"
        policy = legacy_alias_policy(
            [unique, first, colliding],
            authoritative=True,
        )

        self.assertEqual(mqtt_legacy_action("compat", unique, policy), "publish")
        self.assertEqual(mqtt_legacy_action("compat", first, policy), "remove")
        self.assertEqual(mqtt_legacy_action("off", unique, policy), "none")
        self.assertEqual(mqtt_legacy_action("cleanup", unique, policy), "remove")

    def test_lifecycle_cleanup_preserves_an_active_compat_owner(self):
        active = "1234567890456"
        inactive = "9876543210123"
        policy = legacy_alias_policy(
            [active],
            published_account_nos=[active],
            authoritative=True,
        )

        self.assertFalse(mqtt_remove_legacy_on_cleanup("compat", active, policy))
        self.assertTrue(mqtt_remove_legacy_on_cleanup("compat", inactive, policy))
        self.assertFalse(mqtt_remove_legacy_on_cleanup("off", inactive, policy))
        self.assertTrue(mqtt_remove_legacy_on_cleanup("cleanup", active, policy))


if __name__ == "__main__":
    unittest.main()
