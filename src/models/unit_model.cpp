#include "unit_model.h"

const QDBusArgument &operator>>(const QDBusArgument &argument, SystemdUnit &unit) {
    argument.beginStructure();
    argument >> unit.name >> unit.description >> unit.load_state >> unit.active_state
             >> unit.sub_state >> unit.follower >> unit.unit_path >> unit.job_id
             >> unit.job_type >> unit.job_path;
    argument.endStructure();
    return argument;
}

QDBusArgument &operator<<(QDBusArgument &argument, const SystemdUnit &unit) {
    argument.beginStructure();
    argument << unit.name << unit.description << unit.load_state << unit.active_state
             << unit.sub_state << unit.follower << unit.unit_path << unit.job_id
             << unit.job_type << unit.job_path;
    argument.endStructure();
    return argument;
}