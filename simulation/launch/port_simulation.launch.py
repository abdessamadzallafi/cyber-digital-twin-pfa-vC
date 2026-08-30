import os

from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():

    project_dir = os.path.expanduser(
        '~/Downloads/cyber-digital-twin-pfa-vC'
    )

    world_file = os.path.join(
        project_dir,
        'simulation',
        'worlds',
        'port_simulation.world'
    )

    gazebo_ros_dir = get_package_share_directory('gazebo_ros')

    turtlebot3_gazebo_dir = get_package_share_directory(
        'turtlebot3_gazebo'
    )

    # ==========================================================
    # GAZEBO
    # ==========================================================

    gazebo = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                gazebo_ros_dir,
                'launch',
                'gazebo.launch.py'
            )
        ),
        launch_arguments={
            'world': world_file
        }.items()
    )

    # ==========================================================
    # ROBOT STATE PUBLISHER
    # ==========================================================

    robot_state_publisher = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                turtlebot3_gazebo_dir,
                'launch',
                'robot_state_publisher.launch.py'
            )
        )
    )

    # ==========================================================
    # SPAWN TURTLEBOT3
    # ==========================================================

    robot_sdf = os.path.join(
        turtlebot3_gazebo_dir,
        'models',
        'turtlebot3_burger',
        'model.sdf'
    )

    spawn_robot = Node(
        package='gazebo_ros',
        executable='spawn_entity.py',
        arguments=[
            '-entity', 'burger',
            '-file', robot_sdf,
            '-x', '0.0',
            '-y', '0.0',
            '-z', '0.15'
        ],
        output='screen'
    )

    # ==========================================================
    # LAUNCH
    # ==========================================================

    return LaunchDescription([

        gazebo,

        robot_state_publisher,

        TimerAction(
            period=3.0,
            actions=[
                spawn_robot
            ]
        ),

    ])
