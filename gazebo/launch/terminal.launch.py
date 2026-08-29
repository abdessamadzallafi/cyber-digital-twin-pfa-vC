import os
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    # Chemin vers le monde
    world_file = os.path.expanduser('~/Downloads/cyber-digital-twin/gazebo/worlds/terminal_port.world')

    # Lancement de Gazebo (avec plugins ROS)
    gazebo = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            [os.path.join(get_package_share_directory('gazebo_ros'), 'launch', 'gazebo.launch.py')]
        ),
        launch_arguments={'world': world_file}.items()
    )

    # Spawn du drone de surveillance (après 5 secondes pour laisser Gazebo démarrer)
    spawn_drone = TimerAction(
        period=5.0,
        actions=[
            Node(
                package='gazebo_ros',
                executable='spawn_entity.py',
                arguments=[
                    '-entity', 'drone_01',
                    '-file', os.path.join(os.path.dirname(world_file), 'drone.sdf'),
                    '-x', '0.0', '-y', '0.0', '-z', '1.0'
                ],
                output='screen'
            )
        ]
    )

    return LaunchDescription([gazebo, spawn_drone])
